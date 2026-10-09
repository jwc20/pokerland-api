from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from hands import cards
from hands.models import Hand
from hands.tests import add_stream, schema_properties
from tracker.tests_parsing import hand_in

User = get_user_model()


class OutsTests(SimpleTestCase):
    def test_no_outs_against_a_hand_never_shown(self):
        bet, fold = cards.outs(hand_in("steals_and_squeezes.txt", "262300000002"))

        self.assertEqual((bet["street"], bet["villains"], bet["unknown"]), ("flop", [], 1))
        self.assertEqual((bet["event"], fold["event"]), (bet["event"], bet["event"] + 2))  # Bob raised between
        self.assertIsNone(bet["equity"])

    def test_drawing_against_shown_hands(self):
        hand = hand_in("play_money.txt", "262289826745")
        flop, turn = cards.outs(hand)

        self.assertEqual(flop["villains"], [{"name": "Carol", "cards": ["2c", "Ad"]}])
        self.assertEqual((flop["standing"], flop["cards_to_come"]), ("behind", 2))
        self.assertEqual(turn["equity"], 0.0)  # the river can't save king high against trips

    def test_every_card_is_judged(self):
        hand = {
            "hero": "Hero",
            "game": "Hold'em No Limit",
            "players": [{"name": "Hero", "cards": ["Ah", "Kh"]}, {"name": "Villain", "cards": ["Qs", "Qc"]}],
            "events": [
                {"type": "street", "street": "flop", "board": ["Qh", "7h", "2c"]},
                {"type": "street", "street": "turn", "board": ["Qh", "7h", "2c", "3d"]},
                {"type": "check", "street": "turn", "player": "Hero"},
            ],
        }
        [decision] = cards.outs(hand)
        outs = {row["card"] for row in decision["outs"] if row["kind"] == "out"}
        dirty = {row["card"] for row in decision["outs"] if row["kind"] == "dirty"}

        # Seven hearts make a flush; the two that pair the board give the set a full house over it.
        self.assertEqual(outs, {"4h", "5h", "6h", "8h", "9h", "Th", "Jh"})
        self.assertEqual(dirty, {"2h", "3h"})
        self.assertEqual((decision["standing"], decision["rule"]), ("behind", 2 * len(outs)))
        self.assertAlmostEqual(decision["equity"], len(outs) / 44, places=3)

    def test_counterfeits_and_dangers_when_ahead(self):
        hand = {
            "hero": "Hero",
            "game": "Hold'em No Limit",
            "players": [{"name": "Hero", "cards": ["7s", "6s"]}, {"name": "Villain", "cards": ["Ac", "Ad"]}],
            "events": [
                {"type": "street", "street": "flop", "board": ["7d", "6c", "2h"]},
                {"type": "check", "street": "flop", "player": "Hero"},
            ],
        }
        [decision] = cards.outs(hand)
        kinds = {row["card"]: row["kind"] for row in decision["outs"]}

        self.assertEqual(decision["standing"], "ahead")
        self.assertEqual(kinds["Ah"], "danger")  # a set of aces
        self.assertEqual(kinds["2d"], "counterfeit")  # aces and twos beat sevens and sixes


class BoardReaderTests(SimpleTestCase):
    def test_the_nuts_and_the_next_hands(self):
        street = cards.read_board("flop", ["Ad", "2h", "3h"], ["Ac", "Kd"])

        self.assertEqual(
            [row["description"] for row in street["classes"]],
            ["a five-high straight", "three aces", "two pair, aces and threes"],
        )
        self.assertEqual(street["nuts"]["combos"], 16)
        self.assertEqual(street["texture"]["straight_possible"], True)

    def test_where_the_heros_hand_ranks(self):
        street = cards.read_board("flop", ["Kh", "7c", "2d"], ["Kc", "Qd"])
        hero = street["hero"]

        self.assertEqual(hero["description"], "a pair of kings")
        self.assertEqual(
            hero["beaten_by"],
            [
                {"description": "three kings", "combos": 1},
                {"description": "three sevens", "combos": 3},
                {"description": "three twos", "combos": 3},
                {"description": "two pair, kings up", "combos": 12},
                {"description": "two pair, sevens up", "combos": 9},
            ],
        )
        # And the eight ace-kings, kings with a better kicker, and the six pairs of aces.
        self.assertEqual(hero["better"], 1 + 3 + 3 + 12 + 9 + 8 + 6)
        self.assertEqual(hero["better"] + hero["equal"] + hero["worse"], 1081)

    def test_warnings(self):
        flush = cards.read_board("river", ["Jh", "9h", "4h", "2c", "8s"], ["Th", "3h"])
        straight = cards.read_board("river", ["9h", "8d", "7c", "2s", "Kd"], ["6s", "5s"])
        two_pair = cards.read_board("flop", ["Kh", "9c", "4d"], ["9s", "4s"])

        self.assertIn("not_the_nut_flush", flush["hero"]["warnings"])
        self.assertIn("low_straight", straight["hero"]["warnings"])
        self.assertIn("counterfeit_risk", two_pair["hero"]["warnings"])

    def test_an_omaha_hand_is_sampled(self):
        streets = cards.board_reader(hand_in("omaha_eur.txt"))

        self.assertTrue(streets[0]["hero"]["sampled"])


class EquityTests(SimpleTestCase):
    def test_against_a_known_hand(self):
        found = cards.equity(["Ah", "Kh"], ["Qh", "7h", "2c"], {"cards": ["Qs", "Qc"]})

        self.assertEqual((found["exact"], found["combos"]), (True, 1))
        self.assertAlmostEqual(found["equity"], 0.2556, places=3)

    def test_against_a_range_with_card_removal(self):
        found = cards.equity(["Ah", "Kh"], ["Ts", "7c", "2d", "3s"], {"range": "AA, KK"})

        self.assertEqual((found["exact"], found["combos"]), (True, 6))  # three aces and three kings left

    def test_against_a_kind_of_hand(self):
        found = cards.equity(["9s", "8s"], ["Ts", "7h", "2c", "Kd"], {"kind": "top_pair"})

        self.assertTrue(found["exact"])
        self.assertGreater(found["combos"], 0)

    def test_nothing_left_to_hold(self):
        with self.assertRaises(ValueError):
            cards.equity(["Ah", "As"], ["Ad", "7c", "2d"], {"range": "AA"}, dead=["Ac"])


class CardsApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "play_money.txt")
        self.client.force_authenticate(self.user)
        cache.clear()

    def hand(self, number):
        return Hand.objects.get(user=self.user, hand_id=number)

    def test_a_hands_outs(self):
        response = self.client.get(f"/api/hands/{self.hand('262289826745').pk}/outs/")

        self.assertEqual([row["street"] for row in response.data], ["flop", "turn"])
        self.assertEqual(set(response.data[0]), schema_properties("OutsDecision"))

    def test_the_board_reader_is_kept_once_worked_out(self):
        hand = self.hand("262289826745")

        first = self.client.get(f"/api/hands/{hand.pk}/board/").data
        hand.refresh_from_db()
        second = self.client.get(f"/api/hands/{hand.pk}/board/").data

        self.assertEqual([row["street"] for row in first], ["flop", "turn", "river"])
        self.assertEqual(hand.facts["board_reader"]["streets"], first)
        self.assertEqual(first, second)
        self.assertEqual(set(first[0]), schema_properties("BoardStreet"))

    def test_the_equity_calculator(self):
        response = self.client.post(
            "/api/tools/equity/",
            {"hero": ["Ah", "Kh"], "board": ["Qh", "7h", "2c"], "villain": {"cards": ["Qs", "Qc"]}},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertAlmostEqual(response.data["equity"], 0.2556, places=3)

    def test_the_calculator_refuses_bad_questions(self):
        twice = {"hero": ["Ah", "Kh"], "board": ["Ah", "7h", "2c"], "villain": {"range": "QQ"}}
        both = {"hero": ["Ah", "Kh"], "villain": {"range": "QQ", "kind": "top_pair"}}
        two_cards = {"hero": ["Ah", "Kh"], "board": ["Qh", "7h"], "villain": {"range": "QQ"}}

        for body in (twice, both, two_cards):
            with self.subTest(body):
                self.assertEqual(self.client.post("/api/tools/equity/", body, format="json").status_code, 400)

    def test_another_users_hand_is_hidden(self):
        other = User.objects.create_user("bob")
        self.client.force_authenticate(other)

        self.assertEqual(self.client.get(f"/api/hands/{self.hand('262289826745').pk}/outs/").status_code, 404)
