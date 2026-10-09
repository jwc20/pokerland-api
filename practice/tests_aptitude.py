"""The aptitude test over the API: adaptive, graded kinds only, its answers held until the end; and the ratings."""

from unittest import mock

from django.contrib.auth import get_user_model

from practice import aptitude, ratings, sets
from practice.models import Attempt, Scenario, SkillScore
from practice.tests import PracticeTestCase


class AptitudeTestCase(PracticeTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("practice.library.EQUITY_SAMPLES", 2000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self):
        response = self.client.post("/api/practice/tests/", {"tz": "UTC"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def respond(self, state, right=True):
        """Answers the spot a test is asking, rightly or not, and returns the test as it stands after."""
        scenario = Scenario.objects.get(pk=state["spot"]["scenario"]["id"])
        data = self.right_answer(scenario) if right else self.wrong_answer(scenario)
        body = {"scenario": scenario.pk, "tz": "UTC", "time_taken": 20, **data}
        response = self.client.post(f"/api/practice/tests/{state['id']}/answer/", body, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    @staticmethod
    def wrong_answer(scenario):
        kind = scenario.spec["question"]["kind"]
        if kind == "choice":
            return {"choice": (scenario.answer["correct"] + 1) % len(scenario.spec["question"]["options"])}
        if kind == "range":
            return {"hand_range": ""}
        best = scenario.answer.get("best") or [scenario.answer.get("advice", {}).get("action")]
        legal = scenario.spec["legal"]
        for action in ("fold", "check", "call"):
            if action not in best and (action != "check" or legal["can_check"]):
                return {"action": action}
        return {"action": "raise", "amount": legal["max_to"]}


class TestFlowTests(AptitudeTestCase):
    def test_a_test_asks_one_spot_at_a_time_and_holds_its_answers(self):
        state = self.start()

        self.assertEqual((state["planned"], state["answered"]), (aptitude.PLANNED, 0))
        self.assertNotIn("answer", state["spot"]["scenario"])
        after = self.respond(state)
        self.assertEqual(after["answered"], 1)
        self.assertNotIn("grade", after)
        self.assertNotEqual(after["spot"]["scenario"]["id"], state["spot"]["scenario"]["id"])
        self.assertEqual(self.client.get(f"/api/practice/tests/{state['id']}/").status_code, 400)

    def test_the_first_spots_probe_every_skill_and_only_graded_kinds_come_up(self):
        state = self.start()
        skills, gradings = [], set()
        for _ in range(len(sets.SKILLS)):
            skills.append(state["spot"]["scenario"]["skills"][0])
            gradings.add(state["spot"]["scenario"]["grading"])
            state = self.respond(state)

        self.assertEqual(sorted(skills), sorted(sets.SKILLS))
        self.assertLessEqual(gradings, set(aptitude.GRADED))

    def test_the_next_spot_is_the_same_until_it_is_answered(self):
        state = self.start()
        again = self.client.get(f"/api/practice/tests/{state['id']}/next/").data

        self.assertEqual(again["spot"]["scenario"]["id"], state["spot"]["scenario"]["id"])

    def test_only_the_spot_asked_can_be_answered_and_not_through_attempts(self):
        state = self.start()
        other = Scenario.objects.filter(source="library").exclude(pk=state["spot"]["scenario"]["id"]).first()
        body = {"scenario": other.pk, "choice": 0, "action": "fold", "hand_range": "", "tz": "UTC"}

        response = self.client.post(f"/api/practice/tests/{state['id']}/answer/", body, format="json")
        self.assertEqual(response.status_code, 400)
        body = {"scenario": state["spot"]["scenario"]["id"], "set": state["id"], "tz": "UTC", "choice": 0}
        self.assertEqual(self.client.post("/api/practice/attempts/", body, format="json").status_code, 400)

    def test_a_spot_answered_before_isnt_asked_again(self):
        first = self.start()
        asked = first["spot"]["scenario"]["id"]
        self.respond(first)
        self.client.post(f"/api/practice/tests/{first['id']}/end/")

        state = self.start()
        for _ in range(6):
            self.assertNotEqual(state["spot"]["scenario"]["id"], asked)
            state = self.respond(state)

    def test_another_users_test_is_out_of_reach(self):
        state = self.start()
        self.client.force_authenticate(get_user_model().objects.create_user("bob"))

        self.assertEqual(self.client.get(f"/api/practice/tests/{state['id']}/next/").status_code, 404)


class ReportTests(AptitudeTestCase):
    def play(self, right=True):
        state = self.start()
        while state["spot"]:
            state = self.respond(state, right=right)
        response = self.client.get(f"/api/practice/tests/{state['id']}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_a_test_played_through_reports_each_skill_and_spot(self):
        report = self.play()

        self.assertEqual((report["answered"], len(report["spots"])), (aptitude.PLANNED, aptitude.PLANNED))
        self.assertEqual([skill["skill"] for skill in report["skills"]], list(sets.SKILLS))
        for skill in report["skills"]:
            with self.subTest(skill=skill["skill"]):
                self.assertGreater(skill["spots"], 0)
                self.assertIn(skill["label"], skill["words"])
        self.assertEqual({spot["attempt"]["grade"] for spot in report["spots"]}, {"good"})
        self.assertIn("answer", report["spots"][0]["attempt"])
        self.assertAlmostEqual(report["minutes"], aptitude.PLANNED * 20 / 60)

    def test_good_answers_raise_the_ratings_and_lower_the_spots(self):
        report = self.play()

        scores = SkillScore.objects.filter(user=self.user)
        self.assertEqual({score.skill for score in scores}, set(sets.SKILLS))
        self.assertTrue(all(score.rating > ratings.START for score in scores))
        asked = Scenario.objects.filter(pk__in=[spot["scenario"]["id"] for spot in report["spots"]])
        self.assertTrue(all(scenario.difficulty < ratings.first_difficulty(scenario.tier) for scenario in asked))
        self.assertEqual(set(report["skills"][0]["rating"]), {"rating", "deviation", "low", "high", "attempts"})

    def test_misses_show_up_as_gaps_and_the_next_thing_to_practise(self):
        report = self.play(right=False)

        self.assertTrue(any("a gap" in skill["words"] for skill in report["skills"]))
        self.assertIsNotNone(report["next"])
        self.assertIn(report["next"]["skill"], sets.SKILLS)

    def test_ending_early_reports_what_was_answered(self):
        state = self.start()
        state = self.respond(state)
        ended = self.client.post(f"/api/practice/tests/{state['id']}/end/").data

        self.assertIsNotNone(ended["finished"])
        self.assertIsNone(ended["spot"])
        report = self.client.get(f"/api/practice/tests/{state['id']}/").data
        self.assertEqual(report["answered"], 1)
        # One good answer is no gap to practise, and the skills not reached say so.
        self.assertIsNone(report["next"])
        self.assertEqual(sum("not asked in this test" in skill["words"] for skill in report["skills"]), 4)

    def test_tests_are_listed(self):
        state = self.start()
        self.respond(state)

        listed = self.client.get("/api/practice/tests/").data
        self.assertEqual([(test["id"], test["answered"]) for test in listed], [(state["id"], 1)])


class RebuildTests(AptitudeTestCase):
    def test_ratings_rebuild_from_every_graded_answer(self):
        state = self.start()
        for _ in range(4):
            state = self.respond(state)
        before = {score.skill: round(score.rating, 6) for score in SkillScore.objects.filter(user=self.user)}

        rated = sets.rebuild_ratings()

        self.assertEqual(rated, Attempt.objects.exclude(score=None).exclude(weight=0).count())
        after = {score.skill: round(score.rating, 6) for score in SkillScore.objects.filter(user=self.user)}
        self.assertEqual(after, before)

    def test_the_profile_shows_a_rating_once_its_range_is_narrow(self):
        with mock.patch.object(ratings, "SHOWN_DEVIATION", 400):
            state = self.start()
            self.respond(state)
            skills = self.client.get("/api/practice/profile/", {"tz": "UTC"}).data["skills"]

        rated = [skill for skill in skills if skill["rating"]]
        self.assertEqual(len(rated), 1)
        self.assertEqual(rated[0]["rating"]["attempts"], 1)
        self.assertLessEqual(rated[0]["rating"]["low"], rated[0]["rating"]["rating"])
