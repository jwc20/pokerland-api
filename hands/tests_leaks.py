from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from hands.leaks import PRESETS
from hands.stats import proportion
from hands.tests import StatsTests, add_stream, schema_properties

User = get_user_model()


class LeakTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in StatsTests.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def leaks(self, **params):
        response = self.client.get("/api/leaks/", {"tz": "UTC", **params})
        self.assertEqual(response.status_code, 200, response.data)
        return {check["key"]: check for check in response.data}

    def hand_ids(self, **params):
        response = self.client.get("/api/hands/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return {hand["hand_id"] for hand in response.data["results"]}

    def test_every_check_before_the_flop(self):
        self.assertEqual(
            list(self.leaks()),
            [
                "open_limp",
                "open_size",
                "three_bet_size",
                "short_stack_raise",
                "premium_limp",
                "short_buy_in",
                "hands_per_orbit",
            ],
        )

    def test_open_limps_out_of_the_pots_folded_to_the_hero(self):
        check = self.leaks()["open_limp"]

        self.assertEqual(check["share"], proportion(2, 7))
        self.assertEqual((check["net_broken_bb"], check["net_kept_bb"]), (-25.5, -11.9))
        self.assertEqual(
            [(month["month"], month["did"], month["could"]) for month in check["months"]],
            [("2020-09", 0, 2), ("2026-10", 2, 5)],
        )

    def test_sizes_count_the_small_and_the_big_apart(self):
        checks = self.leaks()
        opens, three_bets = checks["open_size"], checks["three_bet_size"]

        # Opens to 3 BB, 3 BB in a tournament, 4.5 over a limper and 6 over three: all within half a big blind.
        self.assertEqual((opens["share"]["did"], opens["share"]["could"], opens["average"]), (0, 4, 4.12))
        # 3-bets of 3.33 and 3.67 times the raise, and a squeeze of 4.67 over a raise and a call.
        self.assertEqual(
            (three_bets["share"]["did"], three_bets["below"], three_bets["above"], three_bets["average"]),
            (2, 0, 2, 3.89),
        )

    def test_premiums_short_buy_ins_and_hands_per_orbit(self):
        checks = self.leaks()

        self.assertEqual(checks["premium_limp"]["share"], proportion(0, 4))  # AK twice, QQ and KK, all raised
        self.assertEqual(checks["short_buy_in"]["share"], proportion(7, 15))  # cash hands under 100 BB
        # 12 hands played in 16, at tables of 2 to 6: 3.88 orbits' worth.
        self.assertEqual((checks["hands_per_orbit"]["share"], checks["hands_per_orbit"]["rate"]), (None, 3.09))

    def test_a_check_with_no_chances(self):
        self.assertEqual(self.leaks()["short_stack_raise"]["share"], proportion(0, 0))

    def test_the_presets_set_the_rules(self):
        response = self.client.patch(
            "/api/leaks/presets/", {"three_bet_x": 3.5, "size_slack": 1.0, "buy_in_bb": 95}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

        checks = self.leaks()

        self.assertEqual(checks["three_bet_size"]["share"]["did"], 0)
        self.assertEqual(checks["short_buy_in"]["share"], proportion(4, 15))  # 50, 80.7, 94 and 94.5 BB

    def test_the_history_lists_the_hands_that_broke_a_rule(self):
        self.assertEqual(self.hand_ids(leak="open_limp"), {"262289826745", "262289596277"})
        self.assertEqual(self.hand_ids(leak="three_bet_size"), {"219396263497", "262300000002"})
        self.assertEqual(self.hand_ids(leak="open_limp", tag="position:SB"), set())
        self.assertEqual(self.client.get("/api/hands/", {"leak": "hands_per_orbit"}).status_code, 400)

    def test_the_page_filters_apply(self):
        self.assertEqual(self.leaks(since="2026-10-01")["open_limp"]["share"], proportion(2, 5))
        self.assertEqual(self.client.get("/api/leaks/", {"group": "river"}).status_code, 400)

    def test_another_users_hands_are_not_counted(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        checks = {check["key"]: check for check in client.get("/api/leaks/").data}

        self.assertEqual((checks["open_limp"]["share"]["could"], checks["hands_per_orbit"]["rate"]), (0, None))

    def test_leaks_need_a_signed_in_user(self):
        self.assertEqual(APIClient().get("/api/leaks/").status_code, 401)
        self.assertEqual(APIClient().get("/api/leaks/presets/").status_code, 401)

    def test_responses_match_the_schema(self):
        check = self.leaks()["open_limp"]
        preset = self.client.get("/api/leaks/presets/").data[0]

        self.assertEqual(set(check), schema_properties("Leak"))
        self.assertEqual(set(check["months"][0]), schema_properties("LeakMonth"))
        self.assertEqual(set(preset), schema_properties("Preset"))


class CoachPresetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.client.force_authenticate(self.user)

    def presets(self):
        return {row["key"]: row["value"] for row in self.client.get("/api/leaks/presets/").data}

    def patch(self, data, status=200):
        response = self.client.patch("/api/leaks/presets/", data, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def test_the_course_values_to_start(self):
        rows = self.client.get("/api/leaks/presets/").data

        self.assertEqual({row["key"]: row["value"] for row in rows}, {k: p["default"] for k, p in PRESETS.items()})
        self.assertEqual(rows[0]["source"], "JHU 3; MIT 5")

    def test_a_value_is_kept_and_null_puts_back_the_course_value(self):
        self.patch({"open_bb": 2.5})
        self.patch({"buy_in_bb": 80})
        self.assertEqual((self.presets()["open_bb"], self.presets()["buy_in_bb"]), (2.5, 80))

        self.patch({"open_bb": None})

        self.assertEqual((self.presets()["open_bb"], self.presets()["buy_in_bb"]), (3.0, 80))

    def test_values_out_of_range_are_rejected(self):
        for data in ({"open_bb": 1}, {"buy_in_bb": 1000}, {"orbit_min": 3}, {"orbit_max": 0.5, "orbit_min": 1}):
            with self.subTest(data=data):
                self.patch(data, status=400)
        self.assertEqual(self.presets()["orbit_min"], 1.0)

    def test_each_user_has_their_own(self):
        self.patch({"open_bb": 2.5})
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        rows = client.get("/api/leaks/presets/").data

        self.assertEqual(next(row["value"] for row in rows if row["key"] == "open_bb"), 3.0)
