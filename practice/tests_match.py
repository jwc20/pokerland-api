"""Coached matches through the API: the coach's stages, the read card, and the debrief."""

import json
import random
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from hands.tests import schema_properties
from practice import matches, sets
from practice.models import CoachedMatch, MatchDecision, RuleProgress

User = get_user_model()


def follow(state):
    """The move the coach advises, sized to the chip as the action bar would size it."""
    advice, legal = state["decision"]["advice"], state["legal"]
    action, amount = advice["action"], None
    if action in ("bet", "raise"):
        if not legal["can_raise"]:
            return {"action": "call" if legal["to_call"] else "check"}
        if advice["to_bb"]:
            to = advice["to_bb"] * state["big_blind"]
        else:
            pot = MatchDecision.objects.get(match_id=state["id"], move__isnull=True).context["pot"]
            to = legal["bet"] + legal["to_call"] + advice["size"] * (pot + legal["to_call"])
        amount = int(min(legal["max_to"], max(legal["min_to"], to)))
    if action == "fold" and legal["can_check"]:
        action = "check"
    return {"action": action, **({"amount": amount} if amount else {})}


class MatchTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.client.force_authenticate(self.user)
        seeded = random.Random(11)
        patcher = mock.patch("random.SystemRandom", lambda: seeded)  # the deal and the bot, repeatable
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, **data):
        response = self.client.post("/api/practice/matches/", data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def post(self, state, path, data=None, status=200):
        response = self.client.post(f"/api/practice/matches/{state['id']}/{path}/", data or {}, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def to_decision(self, state):
        """Plays on, following the coach, until there is a decision with the coach's advice hidden or the end."""
        while not state["finished"] and not state["decision"]:
            state = self.post(state, "next")
        return state

    def play_out(self, state, decide=follow):
        while not state["finished"]:
            if not state["decision"]:
                state = self.post(state, "next")
                continue
            if state["decision"]["stage"] == 2 and not state["decision"]["intent"]:
                state = self.post(state, "intent", {**self.first_legal(state), "reason": "cant_say"})
            if state["decision"]["advice"] is None:
                state = self.post(state, "ask")
            state = self.post(state, "act", {**decide(state), "time_taken": 2})
        return state

    @staticmethod
    def first_legal(state):
        return {"action": "check" if state["legal"]["can_check"] else "call"}


class StartTests(MatchTestCase):
    def test_a_match_deals_its_first_hand(self):
        state = self.start()

        self.assertEqual((state["hand_number"], state["hands_planned"], state["big_blind"]), (1, 30, 100))
        players = {player["name"]: player for player in state["hand"]["players"]}
        self.assertEqual(len(players["You"]["cards"]), 2)
        self.assertEqual(players["Villain"]["cards"], [])
        self.assertEqual(set(state), schema_properties("MatchState"))

    def test_the_bot_stays_hidden(self):
        state = self.start(opponent="station")

        text = json.dumps(self.client.get(f"/api/practice/matches/{state['id']}/").data)

        self.assertNotIn("leak", text)
        players = self.client.get(f"/api/practice/matches/{state['id']}/").data["hand"]["players"]
        self.assertTrue(all(set(player) == schema_properties("HandPlayer") for player in players))
        self.assertEqual(state["opponent"], "station")

    def test_a_named_opponent_plays_that_style(self):
        state = self.start(opponent="rock")

        seat = CoachedMatch.objects.get(pk=state["id"]).table.seats[1]
        self.assertEqual(seat["style"], "rock")
        self.assertIn(seat["leak"], matches.bots.LEAKS)

    def test_matches_need_a_signed_in_user_and_stay_their_own(self):
        state = self.start()
        other = APIClient()
        other.force_authenticate(User.objects.create_user("bob"))

        self.assertEqual(APIClient().post("/api/practice/matches/").status_code, 401)
        self.assertEqual(other.get(f"/api/practice/matches/{state['id']}/").status_code, 404)


class StageTests(MatchTestCase):
    def test_stage_1_names_the_move_and_why(self):
        state = self.to_decision(self.start(coach="1"))
        decision = state["decision"]

        self.assertEqual(decision["stage"], 1)
        self.assertIsNotNone(decision["advice"])
        self.assertTrue(decision["prompt"])

    def test_stage_2_asks_first_and_answers_the_intent(self):
        state = self.to_decision(self.start(coach="2"))

        self.assertIsNone(state["decision"]["advice"])
        self.assertEqual(state["decision"]["prompt"], "What are you thinking here?")
        self.post(state, "intent", self.first_legal(state), status=400)  # a reason is required

        state = self.post(state, "intent", {**self.first_legal(state), "reason": "cant_say"})

        intent = state["decision"]["intent"]
        self.assertIsNotNone(state["decision"]["advice"])
        self.assertFalse(intent["reason_fits"])
        self.assertIn("maybe you shouldn't be betting", intent["reason_note"])

    def test_stage_3_is_quiet_until_asked_and_counts_the_ask(self):
        state = self.to_decision(self.start(coach="3"))
        self.assertIsNone(state["decision"]["advice"])
        self.assertIsNone(state["decision"]["prompt"])

        state = self.post(state, "ask")

        self.assertTrue(state["decision"]["asked"])
        self.assertIsNotNone(state["decision"]["advice"])

    def test_the_time_bank_runs_from_stage_3(self):
        state = self.to_decision(self.start(coach="3"))

        state = self.post(state, "act", {**self.first_legal(state), "time_taken": 20})

        self.assertEqual(state["time_bank"], 60 - (20 - matches.FREE_SECONDS))

    def test_acting_out_of_turn_is_refused(self):
        state = self.start(coach="1")
        while state["decision"]:
            state = self.post(state, "act", follow(state))

        self.post(state, "act", {"action": "check"}, status=400)

    def test_following_the_coach_moves_a_family_up_a_stage(self):
        moved = RuleProgress.objects.filter(user=self.user, stage=2)
        for _ in range(3):  # a match can end early, when a stack goes
            self.play_out(self.start())
            if moved.exists():
                break

        family = moved.first()
        self.assertIsNotNone(family)
        self.assertEqual(family.recent, [])  # a new stage starts its count again


class ReadCardTests(MatchTestCase):
    def test_a_read_can_be_written_and_withdrawn(self):
        state = self.start()

        state = self.post(state, "reads", {"kind": "read", "tag": "bets_big_weak"})
        self.assertEqual([read["tag"] for read in state["read"]["reads"]], ["bets_big_weak"])
        state = self.post(state, "reads", {"kind": "read", "tag": "bets_big_weak", "withdraw": True})

        self.assertEqual(state["read"]["reads"], [])
        self.assertEqual(CoachedMatch.objects.get(pk=state["id"]).read_notes.count(), 1)  # the card keeps it

    def test_notes_are_checked(self):
        state = self.start()

        self.post(state, "reads", {"kind": "read", "tag": "nonsense"}, status=400)
        self.post(state, "reads", {"kind": "showdown", "tag": "just_once"}, status=400)  # which hand?
        self.post(state, "reads", {"kind": "label", "tag": "rock"})

    def test_counts_say_how_many_chances_they_rest_on(self):
        state = self.play_out(self.start(coach="4"))

        card = self.client.get(f"/api/practice/matches/{state['id']}/").data["read"]
        counts = {count["key"]: count for count in card["counts"]}
        self.assertLessEqual(counts["button"]["did"], counts["button"]["could"])
        self.assertGreater(counts["button"]["could"], 0)


class DebriefTests(MatchTestCase):
    def test_the_debrief_waits_for_the_end(self):
        state = self.start()

        response = self.client.get(f"/api/practice/matches/{state['id']}/debrief/")

        self.assertEqual(response.status_code, 400)

    def test_a_match_played_out_has_its_debrief_with_the_bot_revealed(self):
        state = self.play_out(self.start(coach="4"))

        response = self.client.get(f"/api/practice/matches/{state['id']}/debrief/")

        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        seat = CoachedMatch.objects.get(pk=state["id"]).table.seats[1]
        self.assertEqual((data["read"]["style"], data["read"]["leak"]), (seat["style"], seat["leak"]))
        self.assertEqual(data["result_bb"], state["result_bb"])
        self.assertEqual(set(data), schema_properties("Debrief"))

    def test_departures_are_asked_about_and_sent_to_practice(self):
        def contrary(state):
            """Whatever the coach doesn't advise, when the rules allow something else."""
            legal, advice = state["legal"], state["decision"]["advice"]
            for action in ("fold", "check", "call"):
                allowed = {"fold": not legal["can_check"], "check": legal["can_check"], "call": legal["to_call"] > 0}
                if allowed[action] and action not in advice["accepts"]:
                    return {"action": action}
            return follow(state)

        state = self.start(coach="2")
        asked = None
        while not state["finished"] and asked is None:
            if not state["decision"]:
                state = self.post(state, "next")
                continue
            if not state["decision"]["intent"]:
                state = self.post(state, "intent", {**self.first_legal(state), "reason": "price"})
            state = self.post(state, "act", contrary(state))
            asked = state["departure"]
        self.assertIsNotNone(asked)

        state = self.post(state, "departure", {"hand": asked["hand"], "step": asked["step"], "why": "felt"})

        self.assertIsNone(state["departure"])
        self.post(state, "resign")
        debrief = self.client.get(f"/api/practice/matches/{state['id']}/debrief/").data
        self.assertGreaterEqual(debrief["sent"]["count"], 1)
        self.assertIsNotNone(debrief["fix"])

    def test_resigning_ends_the_match(self):
        state = self.start()

        state = self.post(state, "resign")

        self.assertIsNotNone(state["finished"])
        self.assertEqual(self.client.get("/api/practice/matches/").data[0]["id"], state["id"])


class HouseTests(MatchTestCase):
    def test_a_match_plays_by_the_house_playbook(self):
        state = self.start()

        self.assertEqual(state["playbook"], sets.house_playbook().pk)
