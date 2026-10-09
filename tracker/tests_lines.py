"""The bets, the hero's lines and the leak facts tracker.parsing.facts finds in a hand: no database."""

from django.test import SimpleTestCase

from tracker.parsing import equity, facts
from tracker.tests_parsing import hand_in, player_facts


def bets(hand):
    return hand["facts"]["bets"]


def hero_facts(hand):
    return hand["facts"]["hand"]["facts"]["hero"]


class BetTests(SimpleTestCase):
    def test_every_bet_and_raise_in_order_with_its_size(self):
        hand = hand_in("steals_and_squeezes.txt", "262300000002")

        self.assertEqual(
            [(bet["order"], bet["name"], bet["street"], bet["kind"], bet["size"]) for bet in bets(hand)],
            [
                (0, "Bob", "preflop", "raise", 2.0),
                (1, "Alice", "preflop", "raise", 1.867),
                (2, "Alice", "flop", "bet", 0.462),
                (3, "Bob", "flop", "raise", 0.947),
            ],
        )

    def test_how_each_bet_was_answered(self):
        hand = hand_in("steals_and_squeezes.txt", "262300000002")

        self.assertEqual(
            [(bet["outcome"], bet["hero_response"]) for bet in bets(hand)],
            [("raised", "raise"), ("called", ""), ("raised", ""), ("folded", "fold")],
        )

    def test_a_cbet_and_what_its_maker_held(self):
        cbet = bets(hand_in("steals_and_squeezes.txt", "262300000002"))[2]

        self.assertEqual((cbet["cbet"], cbet["made"], cbet["strength"], cbet["opponents"]), (True, "set", "nuts", 1))
        self.assertEqual(cbet["wetness"], 0)

    def test_an_opponents_bet_is_known_only_if_their_cards_were(self):
        hand = hand_in("play_money.txt", "262289806991")

        self.assertEqual({(bet["made"], bet["strength"]) for bet in bets(hand)}, {("", "")})

    def test_a_shown_opponents_strength(self):
        raise_ = bets(hand_in("zoom_usd.txt"))[3]

        self.assertEqual((raise_["name"], raise_["made"], raise_["strength"]), ("Erin", "pocket_pair", "weak"))

    def test_strengths(self):
        self.assertEqual(facts.strength("set", nuts=True), "nuts")
        self.assertEqual(facts.strength("top_pair"), "strong")
        self.assertEqual(facts.strength("second_pair", ["flush_draw"]), "weak")
        self.assertEqual(facts.strength("high_card", ["open_ended"]), "draw")
        self.assertEqual(facts.strength("overcards", ["gutshot"]), "nothing")

    def test_the_nuts(self):
        self.assertTrue(equity.is_nuts(["Kc", "Kd"], ["7c", "2d", "Kh"]))
        self.assertFalse(equity.is_nuts(["7s", "7d"], ["7c", "2d", "Kh"]))
        self.assertTrue(equity.is_nuts(["4h", "5h"], ["Ad", "2h", "3h"]))  # the wheel, with no flush possible


class LineTests(SimpleTestCase):
    def test_the_preflop_raiser_cbets_in_position_and_folds_to_a_raise(self):
        lines = hero_facts(hand_in("steals_and_squeezes.txt", "262300000002"))["lines"]

        self.assertEqual(
            lines,
            {
                "flop": {
                    "role": "raised",
                    "ip": True,
                    "players": 2,
                    "texture": "dry",
                    "first": "bet",
                    "faced": "fold",
                    "outcome": "raised",
                }
            },
        )

    def test_a_caller_out_of_position_checks_then_answers(self):
        flop = hero_facts(hand_in("play_money.txt", "262289806991"))["lines"]["flop"]

        self.assertEqual(
            {key: flop[key] for key in ("role", "ip", "first", "faced")},
            {"role": "called", "ip": False, "first": "check", "faced": "fold"},
        )

    def test_a_limped_pot_and_a_raise_faced_on_the_river(self):
        river = hero_facts(hand_in("play_money.txt", "262289826745"))["lines"]["river"]

        self.assertEqual(
            (river["role"], river["first"], river["faced"], river["texture"]), ("limped", None, "raise", "monotone")
        )

    def test_nobody_has_position_once_everyone_else_is_all_in(self):
        lines = hero_facts(hand_in("side_pots.txt", "262289607882"))["lines"]

        self.assertEqual({line["ip"] for line in lines.values()}, {None})

    def test_the_last_made_hand(self):
        self.assertEqual(hero_facts(hand_in("postflop_leaks.txt", "262400000002"))["final"], "second_pair")
        self.assertIsNone(hero_facts(hand_in("steals_and_squeezes.txt", "262300000001"))["final"])

    def test_textures(self):
        texture = facts.board_texture
        self.assertEqual(facts.texture_class(texture(["9h", "8h", "2h"])), "monotone")
        self.assertEqual(facts.texture_class(texture(["9h", "9c", "2d"])), "paired")
        self.assertEqual(facts.texture_class(texture(["9h", "8h", "7d"])), "wet")
        self.assertEqual(facts.texture_class(texture(["Kh", "7c", "2d"])), "dry")


class SizingFlagTests(SimpleTestCase):
    def test_a_small_bet_on_a_wet_board(self):
        self.assertEqual(hero_facts(hand_in("side_pots.txt", "262289601365"))["flags"], ["small_on_wet"])

    def test_no_flags(self):
        self.assertEqual(hero_facts(hand_in("steals_and_squeezes.txt", "262300000002"))["flags"], [])


class LeakFactTests(SimpleTestCase):
    def test_folding_a_set_on_a_dry_board(self):
        alice = player_facts(hand_in("steals_and_squeezes.txt", "262300000002"), "Alice")

        self.assertEqual((alice["strong_fold_could"], alice["strong_fold_did"]), (1, 1))

    def test_checking_the_river_back_and_winning_the_showdown(self):
        hand = hand_in("postflop_leaks.txt", "262400000001")
        alice, carol = player_facts(hand, "Alice"), player_facts(hand, "Carol")

        self.assertEqual((alice["thin_value_could"], alice["thin_value_did"]), (1, 1))
        self.assertEqual((carol["thin_value_could"], carol["thin_value_did"]), (0, 0))  # she checked first

    def test_betting_when_checked_to_on_the_river_is_no_missed_value(self):
        bob = player_facts(hand_in("postflop_leaks.txt", "262400000002"), "Bob")

        self.assertEqual((bob["thin_value_could"], bob["thin_value_did"]), (1, 0))
