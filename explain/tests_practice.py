"""Explanations of practice spots, coach's lines, debriefs, aptitude tests and sessions."""

import datetime
import json
from unittest import mock

from explain.models import Explanation
from hands.models import Hand, Session
from practice.models import Attempt, MatchDecision, Scenario, ScenarioSet
from practice.tests import NOW, PracticeTestCase
from practice.tests_match import MatchTestCase

USAGE = {"input": 4000, "cached_input": 0, "cache_write": 0, "output": 2000}


class ExplainingMixin:
    def brief(self, kind, pk, status=200, provider="openai"):
        response = self.client.post(
            "/api/explanations/brief/", {"kind": kind, "id": pk, "provider": provider}, format="json"
        )
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def save(self, brief, status=201):
        data = json.loads(brief["input"])
        content = {
            "headline": "What this showed",
            "summary": "A short look back.",
            "story": [{"label": "The spot", "text": "It turned on the price."}],
            "decisions": [
                {"ref": decision["ref"], "verdict": decision["verdict"], "why": "Because.", "instead": None}
                for decision in data.get("decisions", [])
            ],
            "strengths": [],
            "suggestions": [{"priority": "high", "text": "Drill it.", "practice": data["practice_links"][0]}],
            "luck": None,
            "caveats": [],
        }
        body = {
            "kind": brief["kind"],
            "id": brief["id"],
            "provider": "openai",
            "model": "gpt-6.1-sol",
            "brief_hash": brief["hash"],
            "stop": "completed",
            "content": content,
            "usage": USAGE,
        }
        response = self.client.post("/api/explanations/", body, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data


class AttemptTests(ExplainingMixin, PracticeTestCase):
    def answered(self):
        today = self.today()
        for spot in today["spots"]:
            scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
            if scenario.source == "own_hand":
                return self.answer(spot, today["id"])
        raise AssertionError("No spot from the user's own hands")

    def test_an_answered_spot_is_explained_with_its_grade_and_saved_under_it(self):
        attempt = self.answered()

        brief = self.brief("attempt", attempt["id"])
        saved = self.save(brief)

        data = json.loads(brief["input"])
        verdicts = {"good": "kept", "acceptable": "close", "poor": "broke", "ungraded": "none"}
        self.assertEqual(data["decisions"][0]["verdict"], verdicts[attempt["grade"]])
        self.assertEqual(data["spot"]["grade"], attempt["grade"])
        listed = self.client.get("/api/explanations/", {"attempt": attempt["id"]}).data
        self.assertEqual([item["id"] for item in listed], [saved["id"]])

    def test_an_own_hand_spot_names_nobody(self):
        brief = self.brief("attempt", self.answered()["id"])

        names = {player["name"] for hand in Hand.objects.filter(user=self.user) for player in hand.replay["players"]}
        for name in names:
            self.assertNotRegex(brief["input"], rf"\b{name}\b")

    def test_a_tests_spots_wait_for_the_end_of_the_test(self):
        attempt = Attempt.objects.get(pk=self.answered()["id"])
        test = ScenarioSet.objects.create(user=self.user, kind="test", day=NOW.date(), planned=24)
        Attempt.objects.filter(pk=attempt.pk).update(set=test)

        response = self.brief("attempt", attempt.pk, status=409)

        self.assertIn("test is over", response["detail"])


class TestReportTests(ExplainingMixin, PracticeTestCase):
    def test_a_finished_test_is_explained_by_skill_with_its_misses(self):
        response = self.client.post("/api/practice/tests/", {"tz": "UTC"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        test = ScenarioSet.objects.get(pk=response.data["id"])

        self.brief("test", test.pk, status=409)
        ScenarioSet.objects.filter(pk=test.pk).update(finished=NOW)

        brief = self.brief("test", test.pk)
        self.save(brief)
        self.assertEqual(json.loads(brief["input"])["kind"], "test")


class MatchExplanationTests(ExplainingMixin, MatchTestCase):
    def test_a_coach_line_is_explained_once_the_move_is_made(self):
        state = self.to_decision(self.start(coach="1"))
        pending = MatchDecision.objects.get(match_id=state["id"], move__isnull=True)

        self.brief("decision", pending.pk, status=409)
        self.play_out(state)

        decided = MatchDecision.objects.filter(match_id=state["id"], move__isnull=False).first()
        brief = self.brief("decision", decided.pk)
        self.save(brief)
        data = json.loads(brief["input"])
        self.assertTrue(data["coach_said"])
        self.assertNotIn("leak", brief["input"].lower())

    def test_a_debrief_waits_for_the_end_and_sends_nothing_to_practice(self):
        state = self.start(coach="4")
        self.brief("debrief", state["id"], status=409)
        state = self.play_out(state)
        scenarios = Scenario.objects.count()

        brief = self.brief("debrief", state["id"])

        self.assertEqual(Scenario.objects.count(), scenarios)
        data = json.loads(brief["input"])
        styles = ("tight-aggressive", "loose-aggressive", "a calling station", "a rock")
        self.assertIn(data["match"]["opponent_style"], styles)
        self.save(brief)


class SessionExplanationTests(ExplainingMixin, PracticeTestCase):
    def test_a_finished_session_is_explained_with_its_telling_hands_and_no_names(self):
        session = Session.objects.filter(user=self.user).order_by("-hands").first()

        brief = self.brief("session", session.pk)
        saved = self.save(brief)

        data = json.loads(brief["input"])
        self.assertEqual(data["session"]["hands"], session.hands)
        self.assertLessEqual(len(data["telling_hands"]), 10)
        for name in ("Alice", "Bob", "Carol"):
            self.assertNotIn(name, brief["input"])
        self.assertEqual(saved["period_start"], session.start.isoformat().replace("+00:00", "Z"))

    def test_sessions_wait_until_the_user_has_stopped_playing(self):
        session = Session.objects.filter(user=self.user).first()
        latest = Hand.objects.filter(user=self.user).latest("played_at").played_at

        with mock.patch("django.utils.timezone.now", return_value=latest + datetime.timedelta(minutes=5)):
            response = self.client.post(
                "/api/explanations/brief/", {"kind": "session", "id": session.pk, "provider": "google"}, format="json"
            )

        self.assertEqual(response.status_code, 409)

    def test_a_session_explanation_outlives_a_rebuild(self):
        session = Session.objects.filter(user=self.user).first()
        saved = self.save(self.brief("session", session.pk))

        session.delete()

        explanation = Explanation.objects.get(pk=saved["id"])
        self.assertIsNone(explanation.session_id)
        self.assertIsNotNone(explanation.period_start)
