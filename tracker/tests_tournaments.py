"""Tournament facts read from hand histories (tracker.parsing.tournaments): no database."""

from django.test import SimpleTestCase

from tracker.parsing.tournaments import entry, level, roman, tournament_facts
from tracker.tests_parsing import hand_in, hands_in

HEADER = "PokerStars Hand #1: Tournament #2981073415, {} Hold'em No Limit - Level III (25/50) - 2020/09/22 21:05:00 ET"


class EntryTests(SimpleTestCase):
    def test_a_buy_in_and_its_fee(self):
        self.assertEqual(
            entry(HEADER.format("$0.98+$0.12 USD")),
            {"buy_in": 98, "fee": 12, "bounty": 0, "currency": "USD", "play_money": False, "freeroll": False},
        )

    def test_a_bounty_sits_between_the_prize_pool_and_the_fee(self):
        found = entry(HEADER.format("$1+$1+$0.20 USD"))

        self.assertEqual((found["buy_in"], found["bounty"], found["fee"]), (100, 100, 20))

    def test_a_currency_from_its_symbol(self):
        self.assertEqual(entry(HEADER.format("€4.60+€0.40"))["currency"], "EUR")

    def test_play_money_has_no_currency(self):
        found = entry(HEADER.format("1,000+100"))

        self.assertEqual((found["buy_in"], found["fee"], found["currency"], found["play_money"]), (1000, 100, "", True))

    def test_a_freeroll(self):
        found = entry(HEADER.format("Freeroll "))

        self.assertEqual((found["freeroll"], found["buy_in"], found["play_money"]), (True, 0, False))

    def test_a_cash_game_has_no_entry(self):
        self.assertIsNone(entry("PokerStars Hand #1:  Hold'em No Limit ($0.05/$0.10 USD) - 2026/10/04 10:00:00 ET"))


class LevelTests(SimpleTestCase):
    def test_roman_numerals(self):
        numerals = ("I", "IV", "IX", "XIV", "XL", "MCMXC")
        self.assertEqual([roman(numeral) for numeral in numerals], [1, 4, 9, 14, 40, 1990])

    def test_the_level_in_the_first_line(self):
        self.assertEqual(level(HEADER.format("$1+$0.10 USD")), 3)

    def test_a_spin_and_go_names_its_round_first(self):
        header = "PokerStars Hand #1: Tournament #1, $1+$0.10 USD Hold'em No Limit - Match Round I, Level IV (20/40)"

        self.assertEqual(level(header), 4)


class FinishTests(SimpleTestCase):
    def facts(self, *lines):
        return tournament_facts("\n".join([HEADER.format("$1+$1+$0.20 USD"), *lines]))

    def test_a_finish_out_of_the_money(self):
        self.assertEqual(
            self.facts("Carol finished the tournament in 4th place")["finishes"],
            [{"player": "Carol", "place": 4, "prize": None}],
        )

    def test_a_finish_in_the_money(self):
        self.assertEqual(
            self.facts("Bob finished the tournament in 2nd place and received $3.20.")["finishes"],
            [{"player": "Bob", "place": 2, "prize": 320}],
        )

    def test_the_winner(self):
        self.assertEqual(
            self.facts("Alice wins the tournament and receives $10.80 - congratulations!")["finishes"],
            [{"player": "Alice", "place": 1, "prize": 1080}],
        )

    def test_a_bounty_and_a_progressive_knockout(self):
        found = self.facts(
            "Dan wins the $1 bounty for eliminating Eve",
            "Alice wins $0.50 for eliminating Bob and their own bounty increases by $0.50 to $1.50",
            "Carol wins $0.25 for splitting the elimination of Frank and their own bounty increases by $0.25 to $1.25",
        )["knockouts"]

        self.assertEqual(
            found,
            [
                {"player": "Dan", "amount": 100, "eliminated": "Eve"},
                {"player": "Alice", "amount": 50, "eliminated": "Bob"},
                {"player": "Carol", "amount": 25, "eliminated": "Frank"},
            ],
        )

    def test_names_with_spaces_and_dots(self):
        self.assertEqual(
            self.facts("Mr. Big Stack finished the tournament in 13th place")["finishes"][0]["player"], "Mr. Big Stack"
        )


class ExtractTournamentTests(SimpleTestCase):
    def test_a_tournament_hand_carries_its_facts(self):
        hand = hand_in("tournament_finishes.txt", "263100000002")

        self.assertEqual(
            {key: hand["tournament"][key] for key in ("buy_in", "fee", "bounty", "currency", "level")},
            {"buy_in": 100, "fee": 20, "bounty": 100, "currency": "USD", "level": 2},
        )
        self.assertEqual(hand["tournament"]["finishes"], [{"player": "Bob", "place": 3, "prize": None}])
        self.assertEqual(hand["facts"]["hand"]["level"], 2)
        self.assertEqual(hand["facts"]["hand"]["facts"]["tournament"]["knockouts"][0]["player"], "Alice")

    def test_a_cash_hand_has_none(self):
        hand = hand_in("play_money.txt")

        self.assertIsNone(hand["tournament"])
        self.assertIsNone(hand["facts"]["hand"]["level"])
        self.assertNotIn("tournament", hand["facts"]["hand"]["facts"])

    def test_every_hand_of_the_fixture_reads(self):
        self.assertEqual(len(hands_in("tournament_finishes.txt")), 6)
