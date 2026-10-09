"""Their seat: opponents' decisions in the user's hands, played from their chair, and their ranges read from a line."""

import random

from hands import ranges
from practice import theirs
from practice.models import Scenario
from practice.tests import PracticeTestCase


class TheirSeatTestCase(PracticeTestCase):
    FIXTURES = ("side_pots.txt", "play_money.txt", "postflop_leaks.txt", "split_pots.txt")

    def their_set(self):
        response = self.client.post("/api/practice/sets/", {"kind": "their_seat", "tz": "UTC"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data


class TheirMoveTests(TheirSeatTestCase):
    def test_a_move_is_played_from_their_seat_with_their_cards_and_without_yours(self):
        data = self.their_set()
        moves = [spot for spot in data["spots"] if spot["scenario"]["topic"] == "their_action"]

        self.assertTrue(moves)
        for spot in moves:
            scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
            hand = spot["scenario"]["spec"]["hand"]
            with self.subTest(scenario=scenario.pk):
                self.assertEqual(scenario.source, "their_seat")
                self.assertEqual(hand["hero"], scenario.answer["player"])
                self.assertNotEqual(hand["hero"], scenario.hand.hero)
                cards = {player["name"]: player["cards"] for player in hand["players"]}
                self.assertEqual(len(cards[hand["hero"]]), 2)  # theirs, face up
                self.assertEqual(cards[scenario.hand.hero], [])  # yours, hidden from their chair
                # The replay shows a seat's cards from its deal: theirs is dealt, and yours isn't.
                dealt = [(event["player"], event["cards"]) for event in hand["events"] if event["type"] == "deal"]
                self.assertEqual(dealt, [(hand["hero"], cards[hand["hero"]])])
                self.assertIn(f"{hand['hero']}'s seat", spot["scenario"]["spec"]["question"]["prompt"])

    def test_the_answer_says_what_they_did_and_how_it_went_for_them(self):
        data = self.their_set()
        spot = next(spot for spot in data["spots"] if spot["scenario"]["topic"] == "their_action")
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])

        attempt = self.answer(spot, data["id"], **self.right_answer(scenario))
        answer = attempt["answer"]
        self.assertEqual(answer["player"], scenario.answer["player"])
        self.assertIn("action", answer["they_did"])
        self.assertEqual(answer["result"]["hand"], scenario.hand_id)

    def test_spots_are_made_once(self):
        first = {spot["scenario"]["id"] for spot in self.their_set()["spots"]}
        second = {spot["scenario"]["id"] for spot in self.their_set()["spots"]}

        self.assertTrue(first)
        self.assertFalse(first & second)


class TheirRangeTests(TheirSeatTestCase):
    def reads(self):
        found = theirs.spots(self.user, random.Random(1), actions=0, reads=5)
        self.assertTrue(found, "the fixtures should give a range to read")
        return found

    def test_a_range_is_asked_from_your_seat_before_their_cards_are_shown(self):
        for scenario in self.reads():
            hand = scenario.spec["hand"]
            with self.subTest(scenario=scenario.pk):
                self.assertEqual(scenario.spec["question"]["kind"], "range")
                self.assertEqual(hand["hero"], scenario.hand.hero)
                shown = {player["name"]: player["cards"] for player in hand["players"]}
                self.assertEqual(shown[scenario.answer["player"]], [])
                self.assertEqual(hand["events"][-1]["player"], scenario.answer["player"])  # just after their move
                self.assertIn("chances", scenario.answer["assumptions"])
                self.assertIn("in your hands", scenario.answer["assumptions"])
                self.assertTrue(ranges.parse(scenario.answer["range"]))

    def test_answering_shows_their_cards_against_the_stated_range(self):
        scenario = self.reads()[0]
        attempt = self.answer({"scenario": {"id": scenario.pk}}, None, hand_range=scenario.answer["range"])

        self.assertEqual(attempt["grade"], "good")
        self.assertEqual(attempt["answer"]["their_cards"], scenario.answer["their_cards"])
        stated = ranges.parse(attempt["answer"]["range"])
        self.assertEqual(attempt["answer"]["in_stated"], scenario.answer["their_hand"] in stated)


class LineModelTests(TheirSeatTestCase):
    """The stated range's model, on its own."""

    def test_a_call_is_the_band_below_the_raises_it_didnt_make(self):
        self.assertEqual(theirs.stated_range("three_bet", 6), ranges.top(6))
        self.assertEqual(theirs.stated_range("cold_call", 10, 6), ranges.top(16) - ranges.top(6))
        self.assertFalse(theirs.stated_range("cold_call", 10, 6) & ranges.top(6))

    def test_few_chances_lean_on_a_typical_player(self):
        self.assertEqual(theirs.drawn(0, 0, 20), 20)
        self.assertAlmostEqual(theirs.drawn(5, 10, 20), 100 * (5 + 2) / 20)
        self.assertAlmostEqual(theirs.drawn(500, 1000, 20), 100 * 502 / 1010)
