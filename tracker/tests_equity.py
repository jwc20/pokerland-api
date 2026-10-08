import random
from io import StringIO
from itertools import combinations

from django.core.management import call_command
from django.test import SimpleTestCase
from pokerkit import OmahaHoldemHand, StandardHighHand

from tracker.parsing import equity
from tracker.tests_parsing import hand_in, player_facts


def sign(a, b):
    return (a > b) - (a < b)


class ValueTests(SimpleTestCase):
    def test_hands_rank_as_pokerkit_ranks_them(self):
        rng = random.Random(15)
        for _ in range(1500):
            cards = rng.sample(equity.CARDS, 9)
            a, b, board = cards[:2], cards[2:4], cards[4:]
            theirs = sign(*(StandardHighHand.from_game("".join(hole), "".join(board)) for hole in (a, b)))
            with self.subTest(a=a, b=b, board=board):
                self.assertEqual(sign(equity.value(a, board), equity.value(b, board)), theirs)

    def test_omaha_hands_use_two_hole_cards_and_three_of_the_board(self):
        rng = random.Random(16)
        for _ in range(150):
            cards = rng.sample(equity.CARDS, 13)
            a, b, board = cards[:4], cards[4:8], cards[8:]
            theirs = sign(*(OmahaHoldemHand.from_game("".join(hole), "".join(board)) for hole in (a, b)))
            with self.subTest(a=a, b=b, board=board):
                self.assertEqual(sign(equity.value(a, board, omaha=True), equity.value(b, board, omaha=True)), theirs)

    def test_the_rarer_hands(self):
        board = ["Ah", "2h", "3h", "4h", "Kd"]

        self.assertGreater(equity.value(["5h", "Kc"], board), equity.value(["5c", "Ks"], board))  # steel wheel
        self.assertGreater(equity.value(["5c", "2c"], board), equity.value(["Kc", "Ks"], board))  # wheel, trips
        self.assertGreater(equity.value(["Qh", "Jc"], board), equity.value(["Ks", "Kc"], board))  # a flush, trips
        # Three pairs: the best two play, and the third pair's rank can be the kicker.
        self.assertGreater(
            equity.value(["9c", "9d"], ["8c", "8d", "5s", "5h", "2c"]),
            equity.value(["9c", "9d"], ["8c", "8d", "4s", "3h", "2c"]),
        )


class SharesTests(SimpleTestCase):
    def test_every_card_to_come_is_counted_on_the_flop(self):
        yours, theirs, flop = ["Ah", "Kh"], ["Qs", "Qd"], ["2h", "7h", "Tc"]
        wins = 0.0
        left = [card for card in equity.CARDS if card not in {*yours, *theirs, *flop}]
        for run in combinations(left, 2):
            board = [*flop, *run]
            ranked = (StandardHighHand.from_game("".join(hole), "".join(board)) for hole in (yours, theirs))
            wins += (1 + sign(*ranked)) / 2

        (mine, other), exact = equity.shares([yours, theirs], flop)

        self.assertTrue(exact)
        self.assertAlmostEqual(mine, wins / 990)
        self.assertAlmostEqual(mine + other, 1)

    def test_a_tie_splits_the_pot(self):
        (first, second), _ = equity.shares([["2c", "3d"], ["4c", "5d"]], ["Th", "Jh", "Qh", "Kh", "Ah"])

        self.assertEqual((first, second), (0.5, 0.5))

    def test_before_the_flop_the_board_is_sampled(self):
        (aces, kings), exact = equity.shares([["As", "Ad"], ["Ks", "Kd"]], rng=random.Random(1))

        self.assertFalse(exact)
        self.assertAlmostEqual(aces, 0.82, delta=0.03)  # about 82%, as every table says

    def test_against_a_range(self):
        share, error = equity.range_share(["As", "Ad"], [["Kc", "Kh"], ["Qc", "Qh"]], rng=random.Random(2))

        self.assertAlmostEqual(share, 0.81, delta=3 * error + 0.01)


class SidePotTests(SimpleTestCase):
    def test_a_short_stack_plays_for_the_main_pot_alone(self):
        put_in = {"Ann": 100, "Bob": 300, "Cat": 300, "Dan": 50}  # Dan folded

        pots = equity.side_pots(put_in, ["Ann", "Bob", "Cat"])

        self.assertEqual(pots, [(350, ["Ann", "Bob", "Cat"]), (400, ["Bob", "Cat"])])

    def test_one_pot_when_the_stacks_match(self):
        self.assertEqual(equity.side_pots({"Ann": 200, "Bob": 200}, ["Ann", "Bob"]), [(400, ["Ann", "Bob"])])


class AllInTests(SimpleTestCase):
    def test_an_all_in_on_the_flop(self):
        # Ace-king against queens on K-7-2, $4.02 each, with a dead small blind and $0.24 of rake.
        hand = hand_in("zoom_usd.txt", "219396263497")
        alice, erin = player_facts(hand, "Alice"), player_facts(hand, "Erin")

        self.assertEqual((alice["allin_equity"], erin["allin_equity"]), (0.9121, 0.0879))
        kept = 1 - 24 / 809
        self.assertAlmostEqual(alice["ev_net_bb"], (0.9121 * 809 * kept - 402) / 10, places=1)
        # Between them they expect the pot, less the rake, for what they put in.
        self.assertAlmostEqual(alice["ev_net_bb"] + erin["ev_net_bb"], (809 - 24 - 804) / 10)

    def test_side_pots_three_ways(self):
        # Aces all-in short; queens and kings play the side pot as well.
        hand = hand_in("split_pots.txt", "219800000005")
        rows = {name: player_facts(hand, name) for name in ("Alice", "Bob", "Carol")}
        expected = sum(row["ev_net_bb"] + row["invested_bb"] for row in rows.values())

        self.assertAlmostEqual(expected, 23000 * (1 - 1265 / 23000) / 200)  # the pot, rake taken
        self.assertGreater(rows["Bob"]["allin_equity"], rows["Carol"]["allin_equity"])

    def test_the_same_hand_gets_the_same_numbers(self):
        first = player_facts(hand_in("tournament.txt", "219400000001"), "Alice")["ev_net_bb"]

        self.assertEqual(player_facts(hand_in("tournament.txt", "219400000001"), "Alice")["ev_net_bb"], first)

    def test_hands_without_an_all_in_before_the_river_have_none(self):
        hand = hand_in("play_money.txt", "262289822697")

        self.assertEqual({row["allin_equity"] for row in hand["facts"]["players"]}, {None})
        self.assertIsNone(player_facts(hand_in("zoom_usd.txt", "219396263497"), "Bob")["allin_equity"])  # folded

    def test_unknown_cards_or_no_all_in_mean_no_equity(self):
        events = [
            {"type": "post", "street": "preflop", "player": "Ann", "amount": 1},
            {"type": "post", "street": "preflop", "player": "Bob", "amount": 2},
            {"type": "raise", "street": "preflop", "player": "Ann", "amount": 99, "all_in": True},
            {"type": "call", "street": "preflop", "player": "Bob", "amount": 98},
            {"type": "street", "street": "flop", "board": ["2c", "7d", "9h"]},
        ]
        shown = [{"name": "Ann", "cards": ["As", "Ad"]}, {"name": "Bob", "cards": ["Ks", "Kd"]}]
        hidden = [{"name": "Ann", "cards": ["As", "Ad"]}, {"name": "Bob", "cards": []}]
        no_all_in = [{**event, "all_in": False} if event.get("all_in") else event for event in events]

        self.assertIsNotNone(equity.all_in({"events": events, "players": shown}))
        self.assertIsNone(equity.all_in({"events": events, "players": hidden}))
        self.assertIsNone(equity.all_in({"events": no_all_in, "players": shown}))


class BenchmarkCommandTests(SimpleTestCase):
    def test_it_times_each_kind_of_all_in(self):
        out = StringIO()

        call_command("equity_benchmark", repeat=1, stdout=out)

        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 6)
        self.assertTrue(lines[0].startswith("hold'em, heads-up, on the turn: "))
