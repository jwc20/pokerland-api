import datetime
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from explain import catalog
from explain.briefs import build
from explain.models import Explanation, ExplanationTurn
from explain.schema import VERDICTS
from hands.models import Hand, HandNote
from hands.tests import add_stream

User = get_user_model()
NOW = datetime.datetime(2026, 10, 7, 12, tzinfo=datetime.UTC)
USAGE = {"input": 5000, "cached_input": 1000, "cache_write": 0, "output": 2500}
SECRET = "sk-ant-api03-" + "x" * 40


class ExplainTestCase(APITestCase):
    FIXTURES = ("postflop_leaks.txt", "heads_up.txt", "play_money.txt")

    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in self.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A hand with rules that apply: the big blind calls a raise and checks and calls down (rules 2, 3 and 6).
        self.hand = Hand.objects.get(user=self.user, hand_id="262400000002")

    def brief(self, hand=None, provider="anthropic", status=200):
        body = {"kind": "hand", "id": (hand or self.hand).pk, "provider": provider}
        response = self.client.post("/api/explanations/brief/", body, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    @staticmethod
    def content(brief):
        """An answer that passes the checks: every decision with its verdict, and a link from the brief."""
        data = json.loads(brief["input"])
        return {
            "headline": "Calling down second pair against a raiser who kept betting",
            "summary": "A disciplined hand, by the book from start to finish.",
            "story": [{"label": street["street"], "text": "It went on."} for street in data["hand"]["streets"]],
            "decisions": [
                {"ref": decision["ref"], "verdict": decision["verdict"], "why": "Because.", "instead": None}
                for decision in data["decisions"]
            ],
            "strengths": ["You checked to the raiser."],
            "suggestions": [
                {"priority": "high", "text": "Count the price before you call.", "practice": data["practice_links"][0]}
            ],
            "luck": None,
            "caveats": [],
        }

    def save(self, brief, content=None, status=201, **overrides):
        body = {
            "kind": brief["kind"],
            "id": brief["id"],
            "provider": brief["provider"],
            "model": next(model["id"] for model in catalog.MODELS if model["provider"] == brief["provider"]),
            "brief_hash": brief["hash"],
            "effort": "medium",
            "stop": catalog.PROVIDERS[brief["provider"]]["finished"],
            "content": content or self.content(brief),
            "usage": USAGE,
            "request_id": "req_123",
            **overrides,
        }
        response = self.client.post("/api/explanations/", body, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data


class BriefTests(ExplainTestCase):
    def test_the_brief_names_players_by_position_and_leaves_out_names_tables_and_numbers(self):
        brief = self.brief()

        for hidden in ("Alice", "Bob", "Carol", self.hand.table, self.hand.hand_id):
            self.assertNotIn(hidden, brief["input"])
        seats = json.loads(brief["input"])["hand"]["seats"]
        self.assertEqual([seat["player"] for seat in seats], ["Hero", "BTN", "SB"])
        self.assertEqual(seats[0]["cards"], ["Qs", "Jd"])

    def test_each_decision_carries_the_playbooks_verdict_and_numbers(self):
        decisions = json.loads(self.brief()["input"])["decisions"]

        self.assertEqual([decision["ref"] for decision in decisions], [f"d{index}" for index in range(7)])
        self.assertTrue(all(decision["verdict"] in VERDICTS for decision in decisions))
        flop_call = decisions[2]
        self.assertEqual(flop_call["move"], "call 4 bb")
        self.assertEqual(flop_call["verdict"], "kept")
        self.assertEqual(flop_call["rule"]["number"], 6)
        self.assertEqual(flop_call["price"], "4 bb to win a pot of 14.5 bb: a call needs 28%")

    def test_the_brief_carries_the_players_notes_and_purposes_but_not_hidden_cards(self):
        HandNote.objects.create(user=self.user, hand=self.hand, kind="note", street="flop", text="He bets a lot")
        HandNote.objects.create(user=self.user, hand=self.hand, kind="tag", value="hero call")
        hand = Hand.objects.get(user=self.user, hand_id="262289826745")
        HandNote.objects.create(user=self.user, hand=hand, kind="purpose", bet=0, value="value")

        data = json.loads(self.brief()["input"])
        other = json.loads(self.brief(hand)["input"])

        self.assertEqual(data["notes"], [{"on": "flop", "text": "He bets a lot"}])
        self.assertEqual(data["tags"], ["hero call"])
        purposes = [decision.get("your_purpose") for decision in other["decisions"] if "your_purpose" in decision]
        self.assertEqual(purposes, ["value"])
        unshown = [seat for seat in other["hand"]["seats"] if not seat.get("hero") and "cards" not in seat]
        self.assertTrue(unshown)

    def test_only_deepseek_gets_the_schema_in_its_instructions(self):
        self.assertNotIn('"additionalProperties"', self.brief(provider="anthropic")["instructions"])
        self.assertIn('"additionalProperties"', self.brief(provider="deepseek")["instructions"])

    def test_every_provider_gets_the_same_input_and_schema(self):
        briefs = [self.brief(provider=provider) for provider in catalog.PROVIDERS]

        self.assertEqual(len({brief["input"] for brief in briefs}), 1)
        self.assertEqual(len({json.dumps(brief["schema"]) for brief in briefs}), 1)

    def test_the_brief_waits_until_the_session_is_over(self):
        latest = Hand.objects.filter(user=self.user).latest("played_at").played_at
        with mock.patch("django.utils.timezone.now", return_value=latest + datetime.timedelta(minutes=10)):
            response = self.client.post(
                "/api/explanations/brief/", {"kind": "hand", "id": self.hand.pk, "provider": "openai"}, format="json"
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("30 minutes", response.data["detail"])

    def test_hands_dated_in_the_future_dont_keep_explanations_closed(self):
        Hand.objects.filter(pk=self.hand.pk).update(played_at=NOW + datetime.timedelta(days=3))

        self.brief()

    def test_someone_elses_hand_is_not_found(self):
        bob = User.objects.create_user("bob")
        add_stream(bob, "heads_up.txt")
        theirs = Hand.objects.filter(user=bob).first()

        response = self.client.post(
            "/api/explanations/brief/", {"kind": "hand", "id": theirs.pk, "provider": "openai"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_an_unexpected_field_is_refused_by_name_without_its_value(self):
        body = {"kind": "hand", "id": self.hand.pk, "provider": "anthropic", "api_key": SECRET}

        response = self.client.post("/api/explanations/brief/", body, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.data)
        self.assertNotIn(SECRET, json.dumps(response.data))


class SaveTests(ExplainTestCase):
    def test_a_good_answer_is_saved_with_its_cost_and_listed_with_the_hand(self):
        saved = self.save(self.brief())

        self.assertEqual(saved["subject"], self.hand.pk)
        self.assertEqual(saved["provider"], "anthropic")
        self.assertEqual(saved["model"], "claude-opus-5-5")
        self.assertEqual([d["ref"] for d in saved["content"]["decisions"]], [f"d{index}" for index in range(7)])
        # 5,000 fresh at $4, 1,000 cached at $0.20 and 2,500 out at $20, per million tokens.
        self.assertAlmostEqual(saved["cost"], (5000 * 4 + 1000 * 0.2 + 2500 * 20) / 1_000_000)
        listed = self.client.get("/api/explanations/", {"hand": self.hand.pk}).data
        self.assertEqual([item["id"] for item in listed], [saved["id"]])

    def test_decisions_come_back_in_the_briefs_order_and_verdicts_ignore_case(self):
        brief = self.brief()
        content = self.content(brief)
        content["decisions"].reverse()
        content["decisions"][0]["verdict"] = content["decisions"][0]["verdict"].upper()

        saved = self.save(brief, content)

        self.assertEqual([d["ref"] for d in saved["content"]["decisions"]], [f"d{index}" for index in range(7)])

    def test_a_changed_verdict_is_refused_and_nothing_is_saved(self):
        brief = self.brief()
        content = self.content(brief)
        content["decisions"][2]["verdict"] = "broke"

        response = self.save(brief, content, status=400)

        self.assertIn("decisions", response["content"])
        self.assertFalse(Explanation.objects.exists())

    def test_a_missing_or_unknown_decision_is_refused(self):
        brief = self.brief()
        missing = self.content(brief)
        missing["decisions"].pop()
        unknown = self.content(brief)
        unknown["decisions"][0]["ref"] = "d99"

        self.save(brief, missing, status=400)
        self.save(brief, unknown, status=400)

    def test_a_practice_link_must_be_one_of_the_briefs(self):
        brief = self.brief()
        content = self.content(brief)
        content["suggestions"][0]["practice"] = "rule:something_else"

        self.save(brief, content, status=400)

    def test_there_is_at_least_one_suggestion_and_priorities_ignore_case(self):
        brief = self.brief()
        none = self.content(brief)
        none["suggestions"] = []
        shouted = self.content(brief)
        shouted["suggestions"][0]["priority"] = "High"

        self.save(brief, none, status=400)
        saved = self.save(brief, shouted)

        self.assertEqual(saved["content"]["suggestions"][0]["priority"], "high")

    def test_an_answer_too_long_is_refused(self):
        brief = self.brief()
        content = self.content(brief)
        content["headline"] = "x" * 400

        self.save(brief, content, status=400)

    def test_an_answer_that_didnt_finish_is_refused(self):
        response = self.save(self.brief(), stop="max_tokens", status=400)

        self.assertIn("stop", response)

    def test_a_model_not_on_the_list_is_refused(self):
        self.save(self.brief(), model="some-other-model", status=400)

    def test_an_answer_to_an_old_brief_is_a_conflict(self):
        brief = self.brief()
        HandNote.objects.create(user=self.user, hand=self.hand, kind="note", street="", text="Changed meanwhile")

        self.save(brief, status=409)

    def test_a_key_sent_by_mistake_is_refused_and_never_echoed_or_stored(self):
        response = self.save(self.brief(), api_key=SECRET, status=400)

        self.assertIn("api_key", response)
        self.assertNotIn(SECRET, json.dumps(response))
        self.assertFalse(Explanation.objects.exists())

    def test_key_shaped_text_is_removed_before_saving(self):
        brief = self.brief()
        content = self.content(brief)
        content["caveats"] = [f"Your key {SECRET} works", "And AIza" + "B" * 35]

        saved = self.save(brief, content)

        self.assertEqual(saved["content"]["caveats"], ["Your key [key removed] works", "And [key removed]"])

    def test_no_field_can_hold_a_key(self):
        fields = {field.name for field in Explanation._meta.get_fields()} | {
            field.name for field in ExplanationTurn._meta.get_fields()
        }

        self.assertEqual(
            fields,
            {
                "id", "user", "kind", "hand", "attempt", "decision", "debrief", "test", "session", "period_start",
                "period_end", "prompt_version", "brief_hash", "provider", "model", "effort", "content", "usage",
                "cost", "request_id", "useful", "created", "turns", "explanation", "question", "answer",
            },
        )

    def test_a_day_holds_fifty_explanations(self):
        brief = self.brief()
        with mock.patch("explain.views.DAILY_EXPLANATIONS", 1):
            self.save(brief)
            self.save(brief, status=429)

    def test_rating_and_deleting_an_explanation(self):
        saved = self.save(self.brief())

        rated = self.client.patch(f"/api/explanations/{saved['id']}/", {"useful": True}, format="json")
        deleted = self.client.delete(f"/api/explanations/{saved['id']}/")

        self.assertTrue(rated.data["useful"])
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Explanation.objects.exists())

    def test_explanations_go_with_their_hand(self):
        self.save(self.brief())

        self.hand.delete()

        self.assertFalse(Explanation.objects.exists())

    def test_another_users_explanations_are_out_of_reach(self):
        saved = self.save(self.brief())
        bob = APIClient()
        bob.force_authenticate(User.objects.create_user("bob"))

        self.assertEqual(bob.get("/api/explanations/", {"hand": self.hand.pk}).data, [])
        self.assertEqual(bob.delete(f"/api/explanations/{saved['id']}/").status_code, 404)
        self.assertEqual(bob.get(f"/api/explanations/{saved['id']}/turns/brief/").status_code, 404)


class QuestionTests(ExplainTestCase):
    def setUp(self):
        super().setUp()
        self.explanation = self.save(self.brief())

    def turn_brief(self, status=200):
        response = self.client.get(f"/api/explanations/{self.explanation['id']}/turns/brief/")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def ask(self, after, question="Why was the river call fine?", status=201, **overrides):
        body = {
            "after": after,
            "provider": "google",
            "model": "gemini-3.8-flash",
            "question": question,
            "answer": "The price was good against a bettor who bluffs.",
            "stop": "STOP",
            "usage": USAGE,
            **overrides,
        }
        response = self.client.post(f"/api/explanations/{self.explanation['id']}/turns/", body, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def test_the_conversation_holds_the_brief_the_explanation_and_the_questions_so_far(self):
        first = self.turn_brief()
        self.ask(first["after"])

        second = self.turn_brief()

        self.assertEqual(first["after"], 0)
        self.assertEqual([message["role"] for message in first["messages"]], ["user", "assistant"])
        self.assertEqual(json.loads(first["messages"][1]["text"]), self.explanation["content"])
        self.assertEqual(second["after"], 1)
        self.assertEqual(second["messages"][2:], [
            {"role": "user", "text": "Why was the river call fine?"},
            {"role": "assistant", "text": "The price was good against a bettor who bluffs."},
        ])
        self.assertNotIn('"additionalProperties"', second["instructions"])

    def test_a_question_can_go_to_another_provider_and_is_listed(self):
        self.ask(0)

        listed = self.client.get("/api/explanations/", {"hand": self.hand.pk}).data[0]

        answered = [(turn["provider"], turn["model"]) for turn in listed["turns"]]
        self.assertEqual(answered, [("google", "gemini-3.8-flash")])

    def test_a_pasted_key_is_removed_from_the_question(self):
        turn = self.ask(0, question=f"Is my key {SECRET} right?")

        self.assertEqual(turn["question"], "Is my key [key removed] right?")
        self.assertFalse(ExplanationTurn.objects.filter(question__contains="sk-ant").exists())

    def test_an_answer_to_an_old_conversation_is_a_conflict(self):
        self.ask(0)

        self.ask(0, status=409)

    def test_ten_questions_an_explanation(self):
        with mock.patch("explain.views.QUESTIONS_PER_EXPLANATION", 1):
            self.ask(0)
            self.ask(1, status=429)

    def test_questions_stop_when_the_hand_changes(self):
        HandNote.objects.create(user=self.user, hand=self.hand, kind="note", street="river", text="Second thoughts")

        self.turn_brief(status=409)
        self.ask(0, status=409)


class CatalogTests(ExplainTestCase):
    def test_every_provider_has_a_default_model_and_a_finish(self):
        data = self.client.get("/api/explanations/models/").data

        providers = [provider["key"] for provider in data["providers"]]
        self.assertEqual(providers, ["anthropic", "openai", "google", "deepseek"])
        for provider in providers:
            models = [model for model in data["models"] if model["provider"] == provider]
            self.assertEqual(sum(model["default"] for model in models), 1)
            self.assertTrue(all(model["typical_hand"] > 0 for model in models))

    def test_spend_adds_up_this_months_explanations_and_questions(self):
        saved = self.save(self.brief())
        self.client.post(
            f"/api/explanations/{saved['id']}/turns/",
            {"after": 0, "provider": "anthropic", "model": "claude-haiku-5-5", "question": "Why?",
             "answer": "Because.", "stop": "end_turn", "usage": USAGE},
            format="json",
        )

        spend = self.client.get("/api/explanations/spend/", {"tz": "America/New_York"}).data

        self.assertEqual((spend["month"], spend["explanations"], spend["questions"]), ("2026-10", 1, 1))
        haiku = (5000 * 0.10 + 1000 * 0.01 + 2500 * 0.50) / 1_000_000
        self.assertAlmostEqual(spend["cost"], saved["cost"] + haiku)

    def test_deepseek_is_half_price_off_peak(self):
        model = catalog.BY_ID[("deepseek", "deepseek-v4-pro")]
        tuesday_peak = datetime.datetime(2026, 10, 6, 7, tzinfo=datetime.UTC)
        tuesday_night = datetime.datetime(2026, 10, 6, 20, tzinfo=datetime.UTC)
        saturday = datetime.datetime(2026, 10, 10, 7, tzinfo=datetime.UTC)

        self.assertEqual(catalog.price_at(model, tuesday_peak)["input"], 1.32)
        self.assertEqual(catalog.price_at(model, tuesday_night)["input"], 0.66)
        self.assertEqual(catalog.price_at(model, saturday)["input"], 0.66)

    def test_the_list_quotes_peak_prices_whatever_the_hour(self):
        saturday = datetime.datetime(2026, 10, 10, 7, tzinfo=datetime.UTC)
        with mock.patch("django.utils.timezone.now", return_value=saturday):
            models = self.client.get("/api/explanations/models/").data["models"]

        pro = next(model for model in models if model["id"] == "deepseek-v4-pro")
        self.assertEqual(pro["input"], 1.32)
        self.assertAlmostEqual(pro["typical_hand"], (6000 * 1.32 + 3000 * 3.96) / 1_000_000)

    def test_gemini_flash_prices_change_with_the_year(self):
        model = catalog.BY_ID[("google", "gemini-3.8-flash")]

        new_years_eve = datetime.datetime(2026, 12, 31, 23, tzinfo=datetime.UTC)
        self.assertEqual(catalog.price_at(model, new_years_eve)["input"], 0.75)
        self.assertEqual(catalog.price_at(model, datetime.datetime(2027, 1, 1, tzinfo=datetime.UTC))["input"], 1.50)

    @override_settings(EXPLANATIONS_ENABLED=False)
    def test_explanations_switched_off_answer_404(self):
        self.assertEqual(self.client.get("/api/explanations/models/").status_code, 404)
        response = self.client.post(
            "/api/explanations/brief/", {"kind": "hand", "id": self.hand.pk, "provider": "openai"}, format="json"
        )
        self.assertEqual(response.status_code, 404)


class BriefBuilderTests(ExplainTestCase):
    def test_the_hash_changes_with_the_hand_and_the_provider_but_not_by_itself(self):
        first = build("hand", self.hand, "anthropic")
        again = build("hand", self.hand, "anthropic")
        deepseek = build("hand", self.hand, "deepseek")

        self.assertEqual(first.hash, again.hash)
        self.assertNotEqual(first.hash, deepseek.hash)
        self.assertEqual(first.input, deepseek.input)
