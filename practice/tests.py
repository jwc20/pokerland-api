import datetime
import random
from io import StringIO
from unittest import mock

from django.core.management import call_command

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandNote
from hands.tests import add_stream, schema_properties
from practice import sets
from practice.models import Attempt, Review, RuleProgress, Scenario, ScenarioSet
from practice.spots import decisions

User = get_user_model()
TODAY = datetime.date(2026, 10, 7)
NOW = datetime.datetime(2026, 10, 7, 12, tzinfo=datetime.UTC)


class PracticeTestCase(APITestCase):
    FIXTURES = ("steals_and_squeezes.txt", "play_money.txt", "heads_up.txt")

    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in self.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)
        for patcher in (
            mock.patch("django.utils.timezone.now", return_value=NOW),
            mock.patch("practice.generators.SAMPLES", 800),  # push-or-fold equity, sampled: quicker, looser
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def today(self, **params):
        response = self.client.get("/api/practice/sets/today/", {"tz": "UTC", **params})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def answer(self, spot, set_id=None, **data):
        """Answers a spot, in a set if given, rightly unless told otherwise."""
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
        if not data:
            data = self.right_answer(scenario)
        body = {"scenario": scenario.pk, "set": set_id, "tz": "UTC", **data}
        response = self.client.post("/api/practice/attempts/", body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    @staticmethod
    def right_answer(scenario):
        if scenario.spec["question"]["kind"] == "choice":
            return {"choice": scenario.answer["correct"]}
        if scenario.grading == "exact":
            best = scenario.answer["best"][0]
            return {"action": best, **({"amount": scenario.spec["legal"]["max_to"]} if best == "raise" else {})}
        advice = scenario.answer.get("advice")
        if advice and advice["action"] in ("bet", "raise"):
            legal = scenario.spec["legal"]
            return {"action": advice["action"], "amount": legal["min_to"]}
        return {"action": advice["action"] if advice else "fold"}


class TodaySetTests(PracticeTestCase):
    def test_todays_set_has_eight_spots_and_no_answers(self):
        data = self.today()

        self.assertEqual(len(data["spots"]), sets.DAILY_SIZE)
        self.assertEqual([spot["position"] for spot in data["spots"]], list(range(sets.DAILY_SIZE)))
        for spot in data["spots"]:
            with self.subTest(position=spot["position"]):
                self.assertNotIn("answer", spot["scenario"])
                self.assertIsNone(spot["attempt"])

    def test_the_set_is_made_once_a_day(self):
        first = self.today()["id"]

        self.assertEqual(self.today()["id"], first)
        self.assertEqual(ScenarioSet.objects.filter(user=self.user, kind="daily").count(), 1)

    def test_it_mixes_own_decisions_with_their_arithmetic_and_generated_spots(self):
        spots = self.today()["spots"]

        sources = {spot["scenario"]["source"] for spot in spots}
        topics = {spot["scenario"]["topic"] for spot in spots if spot["scenario"]["source"] == "own_hand"}
        self.assertEqual(sources, {"own_hand", "generated"})
        self.assertIn("action", topics)
        self.assertTrue(topics - {"action"})  # an arithmetic question from the user's own decisions

    def test_own_spots_show_no_opponents_cards_and_no_results(self):
        for spot in self.today()["spots"]:
            hand = spot["scenario"]["spec"]["hand"]
            for player in hand["players"]:
                with self.subTest(spot=spot["position"], player=player["name"]):
                    self.assertEqual((player["won"], player["net"]), (0, 0))
                    if player["name"] != hand["hero"]:
                        self.assertEqual(player["cards"], [])
            self.assertFalse(any(event["type"] in ("show", "collect") for event in hand["events"]))

    def test_a_spot_stops_before_the_decision(self):
        spot = next(spot for spot in self.today()["spots"] if spot["scenario"]["source"] == "own_hand")
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])

        events = scenario.hand.replay["events"]

        self.assertEqual(spot["scenario"]["spec"]["hand"]["events"], events[: scenario.step])
        self.assertEqual(events[scenario.step]["player"], scenario.hand.hero)

    def test_hands_less_than_a_day_old_are_left_out(self):
        then = datetime.datetime(2026, 10, 5, 2, 30, tzinfo=datetime.UTC)
        with mock.patch("django.utils.timezone.now", return_value=then):
            self.today()

        recent = Hand.objects.filter(played_at__gte=then - sets.MIN_AGE)
        self.assertTrue(recent.exists())
        self.assertFalse(Scenario.objects.filter(hand__in=recent).exists())

    def test_a_user_without_hands_gets_generated_spots(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        data = client.get("/api/practice/sets/today/").data

        self.assertEqual({spot["scenario"]["source"] for spot in data["spots"]}, {"generated"})
        self.assertEqual(len(data["spots"]), sets.DAILY_SIZE)

    def test_responses_match_the_schema(self):
        data = self.today()
        spot = data["spots"][0]

        self.assertEqual(set(data), schema_properties("PracticeSet"))
        self.assertEqual(set(spot), schema_properties("Spot"))
        self.assertEqual(set(spot["scenario"]["spec"]["hand"]), schema_properties("TableHand"))

    def test_sets_need_a_signed_in_user(self):
        self.assertEqual(APIClient().get("/api/practice/sets/today/").status_code, 401)


class AttemptTests(PracticeTestCase):
    def spot(self, **match):
        return next(
            spot
            for spot in self.today()["spots"]
            if all(spot["scenario"][key] == value for key, value in match.items())
        )

    def test_a_right_choice_is_good_and_shows_the_working(self):
        spot = self.spot(grading="exact", source="own_hand")

        result = self.answer(spot)

        self.assertEqual((result["grade"], result["score"], result["weight"]), ("good", 1.0, 1.0))
        self.assertIn("formula", result["answer"])
        self.assertIn("explanation", result["answer"])

    def test_a_miss_comes_back_tomorrow(self):
        spot = self.spot(grading="exact", source="own_hand")
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
        wrong = (scenario.answer["correct"] + 1) % 4

        result = self.answer(spot, choice=wrong)

        self.assertEqual(result["grade"], "poor")
        review = Review.objects.get(user=self.user, scenario=scenario)
        self.assertEqual((review.box, review.due), (1, TODAY + datetime.timedelta(days=1)))

    def test_a_review_answered_well_moves_up_a_box(self):
        spot = self.spot(grading="exact", source="own_hand")
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
        Review.objects.create(user=self.user, scenario=scenario, box=2, due=TODAY)

        self.answer(spot)

        review = Review.objects.get(user=self.user, scenario=scenario)
        self.assertEqual((review.box, review.due), (3, TODAY + datetime.timedelta(days=7)))

    def test_an_exact_action_reports_the_ev_given_up(self):
        spot = self.spot(source="generated", topic="push_fold")
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
        values = scenario.answer["ev_bb"]
        worst = min(values, key=values.get)
        all_in = {"amount": scenario.spec["legal"]["max_to"]} if worst == "raise" else {}

        result = self.answer(spot, action=worst, **all_in)

        self.assertEqual(result["grade"], "poor")
        self.assertAlmostEqual(result["ev_lost_bb"], round(max(values.values()) - values[worst], 2))

    def test_a_reflection_is_not_graded(self):
        scenario = Scenario.objects.filter(owner=self.user, grading="reflection").first() or self.reflection()
        spot = {"scenario": {"id": scenario.pk}}

        result = self.answer(spot, action="fold", confidence=4)

        self.assertEqual((result["grade"], result["score"], result["weight"]), ("ungraded", None, 0.0))
        self.assertIn("you_did", result["answer"])

    def reflection(self):
        hand = Hand.objects.filter(user=self.user, hero_combo="KK").first()
        data = sets.hand_data(hand)
        context = decisions(data)[-1]
        return sets.action_scenario(self.user, hand, data, context, sets.house_playbook().rules)

    def test_answers_are_recorded_in_the_set(self):
        data = self.today()
        self.answer(data["spots"][0], data["id"])

        spot = self.client.get(f"/api/practice/sets/{data['id']}/").data["spots"][0]

        self.assertEqual(spot["attempt"]["scenario"], spot["scenario"]["id"])
        self.assertEqual(set(spot["attempt"]), schema_properties("AttemptResult"))

    def test_answering_every_spot_finishes_the_set(self):
        data = self.today()
        for spot in data["spots"]:
            self.answer(spot, data["id"])

        self.assertIsNotNone(ScenarioSet.objects.get(pk=data["id"]).finished)

    def test_bad_answers_are_rejected(self):
        spot = self.spot(grading="exact", source="own_hand")
        bad = ({"action": "fold"}, {"choice": 7})
        for data in bad:
            with self.subTest(data=data):
                response = self.client.post(
                    "/api/practice/attempts/", {"scenario": spot["scenario"]["id"], **data}, format="json"
                )
                self.assertEqual(response.status_code, 400)

    def test_another_users_spots_are_out_of_reach(self):
        spot = self.spot(source="own_hand")
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        response = client.post("/api/practice/attempts/", {"scenario": spot["scenario"]["id"], "choice": 0})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.get(f"/api/practice/sets/{self.today()['id']}/").status_code, 404)


class ModeSetTests(PracticeTestCase):
    def test_a_generated_set_drills_one_skill(self):
        response = self.client.post("/api/practice/sets/", {"kind": "generated", "skill": "arithmetic"}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual({spot["scenario"]["skills"][0] for spot in response.data["spots"]}, {"arithmetic"})

    def test_a_my_hands_set_asks_what_you_do(self):
        response = self.client.post("/api/practice/sets/", {"kind": "my_hands"}, format="json")

        self.assertEqual({spot["scenario"]["topic"] for spot in response.data["spots"]}, {"action"})

    def test_a_generated_set_needs_its_skill(self):
        response = self.client.post("/api/practice/sets/", {"kind": "generated"}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_hands_flagged_to_review_come_first_however_long_ago(self):
        flagged = Hand.objects.get(hand_id="262289811345")
        HandNote.objects.create(user=self.user, hand=flagged, kind="review", value="to_review")

        with mock.patch.object(sets, "RECENT_HANDS", 1):  # only the latest hand counts as recent
            picked = sets.own_decisions(self.user, random.Random(1))

        self.assertEqual(picked[0][1], flagged)
        self.assertEqual({hand.hand_id for _, hand, _, _ in picked}, {"262300000002", "262289811345"})


class ProfileTests(PracticeTestCase):
    def test_skills_with_their_ranges_and_the_streak(self):
        for spot in self.today()["spots"]:
            self.answer(spot)

        profile = self.client.get("/api/practice/profile/", {"tz": "UTC"}).data

        arithmetic = next(skill for skill in profile["skills"] if skill["skill"] == "arithmetic")
        self.assertGreater(arithmetic["could"], 0)
        self.assertEqual(arithmetic["pct"], 100.0)
        self.assertLess(arithmetic["ci_low"], 100.0)
        self.assertEqual((profile["current_streak"], profile["today"]), (1, "2026-10-07"))
        self.assertEqual(set(profile), schema_properties("PracticeProfile"))

    def test_again_later_puts_a_spot_in_the_first_box(self):
        spot = self.today()["spots"][0]

        response = self.client.post("/api/practice/reviews/", {"scenario": spot["scenario"]["id"]}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["box"], 1)
        self.assertEqual(self.client.get("/api/practice/profile/").data["reviews_due"], 0)

    def test_a_rule_of_thumb_counts_half(self):
        scenario = Scenario.objects.create(
            source="generated",
            topic="action",
            spec={"question": {"kind": "action"}},
            answer={"advice": {"action": "check", "accepts": ["check"], "rule": "oop_check_to_raiser"}},
            grading="rule",
            skills=["postflop"],
        )

        sets.record(self.user, scenario, None, {"action": "bet", "amount": 100}, TODAY)

        attempt = Attempt.objects.get(scenario=scenario)
        self.assertEqual((attempt.grade, attempt.weight, attempt.rule), ("poor", 0.5, "oop_check_to_raiser"))


class PlaybookTests(PracticeTestCase):
    def book(self, **params):
        response = self.client.get("/api/practice/hands/by-the-book/", {"playbook": self.playbook.pk, **params})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def setUp(self):
        super().setUp()
        self.playbook = sets.house_playbook()

    def test_the_house_playbooks_are_listed(self):
        data = self.client.get("/api/practice/playbooks/").data

        starter = next(playbook for playbook in data if playbook["key"] == "starter-heads-up")
        self.assertEqual((starter["house"], starter["rule_count"], starter["version"]), (True, 13, 1))

    def test_a_playbooks_cards_and_the_users_stage_in_each_family(self):
        RuleProgress.objects.create(user=self.user, playbook_key=self.playbook.key, family="sizing", stage=3)

        data = self.client.get(f"/api/practice/playbooks/{self.playbook.pk}/").data

        self.assertEqual([rule["number"] for rule in data["rules"]], list(range(1, 14)))
        stages = {family["family"]: family["stage"] for family in data["families"]}
        self.assertEqual((stages["sizing"], stages["button"]), (3, 1))
        self.assertEqual(set(data), schema_properties("PlaybookDetail"))

    def test_by_the_book_counts_each_rule_in_the_users_hands(self):
        data = self.book()

        rules = {row["rule"]: (row["did"], row["could"]) for row in data["rules"]}
        self.assertEqual(rules["price_to_call"], (4, 6))
        self.assertEqual(rules["button_raise_every_hand"], (0, 1))
        self.assertNotIn("no_bluffs_vs_caller", rules)  # an adjustment needs a read
        self.assertEqual(set(data), {"hands", "rules"})

    def test_by_the_book_lists_where_a_rule_applied(self):
        [chance] = self.book(rule="button_raise_every_hand")["chances"]

        # Heads-up on the button with seven-deuce, the playbook raises; Alice folded.
        self.assertEqual((chance["hand_id"], chance["step"], chance["followed"]), ("219700000004", 3, False))
        self.assertEqual(chance["move"]["action"], "fold")

    def test_a_rule_must_be_one_of_the_playbooks(self):
        response = self.client.get("/api/practice/hands/by-the-book/", {"playbook": self.playbook.pk, "rule": "x"})

        self.assertEqual(response.status_code, 400)


class GenerateCommandTests(PracticeTestCase):
    def test_the_pool_fills_to_its_size(self):
        call_command("practice_generate", per_skill=3, skill="arithmetic", stdout=StringIO())
        call_command("practice_generate", per_skill=3, skill="arithmetic", stdout=StringIO())  # already full

        topics = sets.GENERATED["arithmetic"][1]
        self.assertEqual(Scenario.objects.filter(source="generated", topic__in=topics).count(), 3)
