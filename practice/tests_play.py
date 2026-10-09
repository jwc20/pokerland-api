"""Play it out: tables of two to nine against bots, from a deal or from one of the user's own decisions."""

import datetime
import random
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone

from hands.models import Opponent
from practice import play, sets
from practice.models import PracticeTable, Scenario
from practice.tests import PracticeTestCase


def posts(hand):
    """How many blinds and antes a stored hand's players posted."""
    return sum(event["type"] == "post" for event in hand.replay["events"])


class PlayTestCase(PracticeTestCase):
    FIXTURES = ("steals_and_squeezes.txt", "play_money.txt", "side_pots.txt", "postflop_leaks.txt")

    def start(self, **body):
        response = self.client.post("/api/practice/tables/", body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def move(self, state):
        """A plain move for whoever plays the user's seat: check if free, else call, else fold."""
        legal = state["legal"]
        action = "check" if legal["can_check"] else "call"
        response = self.client.post(f"/api/practice/tables/{state['id']}/act/", {"action": action}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def finish_hand(self, state):
        while not state["hand_over"]:
            state = self.move(state)
        return state

    def next(self, state):
        response = self.client.post(f"/api/practice/tables/{state['id']}/next/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class DealTests(PlayTestCase):
    def test_a_table_seats_you_and_bots_of_a_style(self):
        state = self.start(seats=6, opponents="station")

        self.assertEqual(len(state["seats"]), 6)
        heroes = [seat for seat in state["seats"] if seat["hero"]]
        self.assertEqual([seat["name"] for seat in heroes], [play.HERO])
        bots = [seat for seat in state["seats"] if not seat["hero"]]
        self.assertEqual({seat["label"] for seat in bots}, {"Calling station"})
        self.assertEqual(state["hand"]["hero"], play.HERO)
        self.assertEqual(len(state["hand"]["players"]), 6)
        self.assertTrue(state["legal"] or state["hand_over"])

    def test_hands_play_through_and_the_next_one_is_dealt(self):
        state = self.finish_hand(self.start(seats=9, opponents="mixed", stack_bb=50))
        self.assertIsNotNone(state["hand_net_bb"])
        self.assertIsNone(state["legal"])

        after = self.next(state)
        self.assertEqual((after["hand_number"], after["hands_played"]), (2, 1))
        self.assertNotEqual(after["hand"]["button_seat"], state["hand"]["button_seat"])

    def test_the_bots_cards_stay_hidden_until_they_are_shown(self):
        for _ in range(4):
            state = self.finish_hand(self.start(seats=3, opponents="lag"))
            shown = {event["player"] for event in state["hand"]["events"] if event["type"] == "show"}
            for player in state["hand"]["players"]:
                if player["name"] not in (play.HERO, *shown):
                    self.assertEqual(player["cards"], [])

    def test_moves_out_of_turn_or_after_the_hand_are_refused(self):
        state = self.finish_hand(self.start(seats=2, opponents="rock"))

        response = self.client.post(f"/api/practice/tables/{state['id']}/act/", {"action": "fold"}, format="json")
        self.assertEqual(response.status_code, 400)
        live = self.start(seats=2, opponents="rock")
        if not live["hand_over"]:
            self.assertEqual(self.client.post(f"/api/practice/tables/{live['id']}/next/").status_code, 400)

    def test_a_busted_stack_buys_in_again(self):
        state = self.finish_hand(self.start(seats=2, opponents="tag"))
        table = PracticeTable.objects.get(pk=state["id"])
        table.seats[0]["stack"] = 0
        table.save()

        after = self.next(state)
        hero = next(player for player in after["hand"]["players"] if player["name"] == play.HERO)
        self.assertEqual(hero["stack"], 100 * play.BLINDS[1])

    def test_bots_can_be_modelled_on_your_own_opponents(self):
        with mock.patch.object(play, "MIN_HANDS", 1):
            state = self.start(seats=4, opponents="mine")

        modelled = [seat for seat in state["seats"] if seat["based_on"]]
        self.assertTrue(modelled)
        for seat in modelled:
            opponent = Opponent.objects.get(pk=seat["based_on"]["id"], user=self.user)
            self.assertEqual((seat["name"], seat["based_on"]["hands"]), (opponent.name, opponent.hands))
            self.assertEqual(seat["label"], f"Modelled on {opponent.name}")

    def test_tables_are_your_own(self):
        state = self.start(seats=2)
        self.client.force_authenticate(get_user_model().objects.create_user("bob"))

        self.assertEqual(self.client.get(f"/api/practice/tables/{state['id']}/").status_code, 404)
        self.assertEqual(self.client.get("/api/practice/tables/").data, [])


class SpotTests(PlayTestCase):
    def own_spots(self):
        """Spots from the user's hold'em hands with a decision after the flop, in a fixed order."""
        sets.mode_set(self.user, "my_hands", datetime.date(2026, 10, 7), rng=random.Random(0))
        spots = Scenario.objects.filter(owner=self.user, source="own_hand", hand__game="Hold'em No Limit")
        return [spot for spot in spots.order_by("pk") if spot.answer["context"]["street"] != "preflop"]

    def own_spot(self):
        """A spot from a hand a practice table can seat: only the two blinds posted, as most hands have."""
        return next(spot for spot in self.own_spots() if posts(spot.hand) == 2)

    def test_a_spot_plays_its_hand_on_from_the_decision(self):
        scenario = self.own_spot()
        state = self.start(scenario=scenario.pk)

        stored = scenario.hand.replay["events"][: scenario.step]
        kinds = ("post", "fold", "check", "call", "bet", "raise")
        mine = [(e["type"], e.get("player"), e.get("amount")) for e in state["hand"]["events"] if e["type"] in kinds]
        theirs = [(e["type"], e.get("player"), e.get("amount")) for e in stored if e["type"] in kinds]
        self.assertEqual(mine, theirs)
        self.assertEqual(state["hand"]["hero"], scenario.hand.hero)
        self.assertEqual(state["legal"]["to_call"], scenario.spec["legal"]["to_call"])
        self.assertEqual(state["spot"]["scenario"], scenario.pk)
        self.assertTrue(state["spot"]["on_script"])
        labels = {seat["label"] for seat in state["seats"] if not seat["hero"]} - {"A typical player"}
        self.assertEqual(labels, {f"Modelled on {seat['name']}" for seat in state["seats"] if seat["based_on"]})

    def test_the_cards_dealt_by_then_stay(self):
        scenario = self.own_spot()
        state = self.start(scenario=scenario.pk)

        before = scenario.hand.replay["events"][: scenario.step]
        board = next(event["board"] for event in reversed(before) if event["type"] == "street")
        dealt = next(event["board"] for event in reversed(state["hand"]["events"]) if event["type"] == "street")
        self.assertEqual(dealt, board)
        hero = next(player for player in state["hand"]["players"] if player["name"] == scenario.hand.hero)
        self.assertEqual(hero["cards"], scenario.hand.hero_cards)

    def test_leaving_the_line_hands_the_others_to_the_bots(self):
        scenario = self.own_spot()
        state = self.start(scenario=scenario.pk)
        did = scenario.answer["you_did"]["action"]
        legal = ("check",) if state["legal"]["can_check"] else ("fold", "call")
        other = next(action for action in legal if action != did)

        response = self.client.post(f"/api/practice/tables/{state['id']}/act/", {"action": other}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["spot"]["on_script"])

    def test_a_hand_with_a_post_a_table_cant_seat_is_refused_not_broken(self):
        # A player joining posts a big blind out of turn, which a practice table doesn't seat.
        scenario = next(spot for spot in self.own_spots() if posts(spot.hand) > 2)

        response = self.client.post("/api/practice/tables/", {"scenario": scenario.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("can't be played out here", str(response.data))
        self.assertFalse(PracticeTable.objects.filter(scenario=scenario).exists())

    def test_only_your_own_hands_a_day_old_can_be_played_out(self):
        scenario = self.own_spot()
        scenario.hand.played_at = timezone.now() - datetime.timedelta(hours=2)
        scenario.hand.save()

        response = self.client.post("/api/practice/tables/", {"scenario": scenario.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        generated = sets.generated_scenario("arithmetic", random.Random(1))
        response = self.client.post("/api/practice/tables/", {"scenario": generated.pk}, format="json")
        self.assertEqual(response.status_code, 400)
