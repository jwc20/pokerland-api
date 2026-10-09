from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from hands.stats import proportion
from hands.tests import StatsTests, add_stream, schema_properties
from tracker.parsing.facts import STATS

User = get_user_model()


class ReportTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in StatsTests.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def get(self, url, **params):
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def groups(self, group_by, **params):
        return [(group["key"], group["hands"]) for group in self.get("/api/stats/", group_by=group_by, **params)]


class GroupingTests(ReportTests):
    def test_by_situation_before_the_flop(self):
        self.assertEqual(self.groups("situation"), [("unopened", 7), ("limped", 4), ("raised", 5)])

    def test_by_effective_stack(self):
        self.assertEqual(self.groups("stack_depth"), [("20-40", 1), ("40-100", 7), ("100+", 8)])

    def test_by_m_zone_in_tournaments(self):
        self.assertEqual(self.groups("m_zone"), [("value", 1)])  # M 16.6

    def test_by_starting_hand_group_without_omaha(self):
        self.assertEqual(
            self.groups("hand_group"),
            [("premium", 4), ("medium_pair", 1), ("big_ace", 1), ("weak_ace", 1), ("junk", 8)],
        )

    def test_by_combo(self):
        combos = dict(self.groups("combo"))

        self.assertEqual((len(combos), combos["AKo"], combos["KK"]), (14, 2, 1))

    def test_by_the_biggest_bet_after_the_flop(self):
        self.assertEqual(
            self.groups("bet_size"),
            [("under_third", 1), ("third_half", 2), ("half_three_quarters", 1), ("pot_plus", 2)],
        )

    def test_by_opponent_the_most_played_first(self):
        self.assertEqual(self.groups("opponent", limit=3), [("Bob", 12), ("Carol", 10), ("Dave", 9)])

    def test_first_decisions_and_shoves(self):
        [group] = self.get("/api/stats/")

        moves = {"fold": 1, "check": 4, "call": 4, "raise": 7}
        self.assertEqual(group["first_actions"], {move: proportion(count, 16) for move, count in moves.items()})
        self.assertEqual(group["shove"], proportion(0, 7))

    def test_groupings_combine_with_the_filters(self):
        self.assertEqual(self.groups("situation", tag="position:BTN"), [("unopened", 3), ("limped", 1), ("raised", 1)])

    def test_responses_match_the_schema(self):
        [group] = self.get("/api/stats/", group_by="situation")[:1]

        self.assertEqual(set(group), schema_properties("StatGroup"))


class SizingTests(ReportTests):
    def test_bets_by_street_size_and_strength(self):
        report = self.get("/api/stats/sizing/")
        flop, turn, river = report["streets"]

        self.assertEqual([street["street"] for street in report["streets"]], ["flop", "turn", "river"])
        self.assertEqual((flop["bets"], flop["strong"]), (5, proportion(4, 5)))
        self.assertEqual(
            [(bucket["key"], bucket["bets"]) for bucket in flop["buckets"]],
            [("under_third", 2), ("third_half", 1), ("half_three_quarters", 1), ("pot_plus", 1)],
        )
        self.assertEqual(
            flop["buckets"][0]["strengths"], {"nothing": 1, "draw": 0, "weak": 0, "strong": 1, "nuts": 0}
        )
        self.assertEqual(flop["buckets"][1]["strengths"]["nuts"], 1)  # top set
        self.assertEqual((turn["bets"], river["bets"], river["strong"]), (2, 3, proportion(1, 3)))

    def test_too_few_bets_tell_nothing(self):
        self.assertEqual({street["tell"] for street in self.get("/api/stats/sizing/")["streets"]}, {None})

    def test_flags(self):
        flags = {row["flag"]: (row["hands"], row["of"]) for row in self.get("/api/stats/sizing/")["flags"]}

        self.assertEqual(flags, {"overbet_bluff": (0, 6), "small_on_wet": (1, 6), "same_chips_barrel": (0, 6)})

    def test_the_filters_apply(self):
        self.assertEqual(self.get("/api/stats/sizing/", tag="format:tournament")["streets"], [])

    def test_responses_match_the_schema(self):
        self.assertEqual(set(self.get("/api/stats/sizing/")), schema_properties("SizingReport"))


class LinesTests(ReportTests):
    def spots(self, street="flop"):
        report = self.get("/api/stats/lines/")
        found = next(row for row in report["streets"] if row["street"] == street)
        return {(spot["role"], spot["ip"]): spot for spot in found["spots"]}

    def test_the_preflop_raiser_in_position(self):
        spot = self.spots()["raised", True]

        self.assertEqual((spot["hands"], spot["bet"], spot["fold"]), (2, proportion(2, 2), proportion(1, 1)))

    def test_a_caller_out_of_position(self):
        spot = self.spots()["called", False]

        self.assertEqual(spot["hands"], 4)
        # Two checks to fold to a bet, and in Omaha a check-raise: three times able to bet first, none taken.
        self.assertEqual(spot["bet"], proportion(0, 3))
        self.assertEqual((spot["fold"], spot["raise"]), (proportion(3, 4), proportion(1, 4)))

    def test_by_texture(self):
        textures = {row["texture"]: row["hands"] for row in self.spots()["raised", True]["textures"]}

        self.assertEqual(textures, {"paired": 1, "dry": 1})

    def test_the_turn_after_a_called_cbet(self):
        report = self.get("/api/stats/lines/")
        turn = next(row for row in report["barrels"] if row["street"] == "turn")

        self.assertEqual((turn["hands"], turn["barrel"]), (1, proportion(1, 1)))

    def test_responses_match_the_schema(self):
        self.assertEqual(set(self.get("/api/stats/lines/")), schema_properties("LinesReport"))


class DictionaryTests(ReportTests):
    def test_every_statistic_and_its_definition(self):
        rows = self.get("/api/stats/dictionary/")

        self.assertEqual([row["key"] for row in rows], [*STATS, "aggression"])
        self.assertEqual(rows[0]["definition"], STATS["vpip"])
