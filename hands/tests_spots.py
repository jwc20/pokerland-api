import json

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from hands import ranges
from hands.filters import PLAYED, UTC
from hands.models import Hand, Opponent, Spot
from hands.spots import SpotError, shareable, spot_fields, spot_filter, validate
from hands.tests import StatsTests, add_stream, schema_properties

User = get_user_model()

BUTTON = {"field": "position", "value": ["BTN"]}
UNOPENED = {"field": "situation", "value": ["unopened"]}


class SpecValidationTests(SimpleTestCase):
    def assertInvalid(self, spec, message):
        with self.assertRaisesMessage(SpotError, message):
            validate(spec)

    def test_a_condition_comes_back_tidied(self):
        self.assertEqual(validate({"field": "range", "value": " TT+ "}), {"field": "range", "value": "TT+"})

    def test_groups_nest(self):
        spec = {"all": [BUTTON, {"not": {"any": [UNOPENED, {"field": "saw_flop", "value": True}]}}]}

        self.assertEqual(validate(spec), spec)

    def test_an_unknown_condition(self):
        self.assertInvalid({"field": "luck", "value": 1}, "spec.field: 'luck' is not a condition.")

    def test_a_choice_that_isnt_one(self):
        self.assertInvalid({"field": "position", "value": ["XX"]}, "spec.value: 'XX' is not one of")

    def test_a_parameter_the_condition_doesnt_take(self):
        self.assertInvalid({"field": "position", "value": ["BTN"], "street": "flop"}, "not street")

    def test_a_parameter_the_condition_needs(self):
        self.assertInvalid({"field": "made", "value": ["set"]}, "spec.street: made needs it.")

    def test_a_range_needs_an_end(self):
        self.assertInvalid({"field": "pot_bb"}, "give min, max or both")

    def test_range_notation_is_read(self):
        self.assertInvalid({"field": "range", "value": "TT+, XYZ"}, "Not a range: 'XYZ'")

    def test_where_the_error_is(self):
        self.assertInvalid({"all": [BUTTON, {"not": {"field": "top", "value": 120}}]}, "spec.all[1].not.value")

    def test_a_group_is_one_thing(self):
        self.assertInvalid({"all": [], "any": []}, "a group is one of all, any or not")

    def test_too_deep(self):
        spec = BUTTON
        for _ in range(7):
            spec = {"not": spec}
        self.assertInvalid(spec, "nested more than 5 deep")

    def test_the_fields_and_their_choices(self):
        fields = {row["field"]: row for row in spot_fields()}

        self.assertIn("BTN", fields["position"]["choices"]["value"])
        self.assertEqual(fields["made"]["required"], ["street", "value"])
        self.assertEqual(fields["pot_bb"]["required"], [])

    def test_sharing_leaves_out_players(self):
        players = {"field": "opponent", "value": ["Bob"]}
        spec = {"all": [BUTTON, players, {"not": {"field": "tournament", "value": ["1"]}}]}

        self.assertEqual(shareable(spec), {"all": [BUTTON]})


class RangeTests(SimpleTestCase):
    def test_notation(self):
        self.assertEqual(ranges.parse("TT+"), {"AA", "KK", "QQ", "JJ", "TT"})
        self.assertEqual(ranges.parse("A9s+"), {"A9s", "ATs", "AJs", "AQs", "AKs"})
        self.assertEqual(ranges.parse("KTo+"), {"KTo", "KJo", "KQo"})
        self.assertEqual(ranges.parse("T9s-T6s"), {"T9s", "T8s", "T7s", "T6s"})
        self.assertEqual(ranges.parse("55-22"), {"22", "33", "44", "55"})
        self.assertEqual(ranges.parse("AK, 72o"), {"AKs", "AKo", "72o"})
        self.assertEqual(len(ranges.parse("any")), 169)

    def test_bad_notation(self):
        for notation in ("AAs", "XX", "AKs-AQo", "T9-"):
            with self.subTest(notation), self.assertRaises(ValueError):
                ranges.parse(notation)

    def test_the_grid_and_its_combos(self):
        self.assertEqual(ranges.HANDS[:3], ("AA", "AKs", "AQs"))
        self.assertEqual(ranges.HANDS[13:15], ("AKo", "KK"))
        self.assertEqual(sum(ranges.combo_count(hand) for hand in ranges.HANDS), 1326)

    def test_the_top_of_the_ranking(self):
        self.assertEqual(ranges.RANKING[:3], ["AA", "KK", "QQ"])
        self.assertEqual(ranges.RANKING[-1], "32o")
        top = ranges.top(5)
        self.assertEqual(top, {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "AKs", "AQs", "77", "AJs", "AKo"})
        self.assertLess(sum(ranges.combo_count(hand) for hand in top) / 1326, 0.06)

    def test_groups_and_holdings(self):
        hands = ("AKo", "JJ", "88", "33", "AQs", "JTs", "KQo", "A5s", "72o")
        groups = ["premium", "big_pair", "medium_pair", "small_pair", "big_ace", "suited_connector", "trouble"]
        self.assertEqual([ranges.group_of(hand) for hand in hands], [*groups, "weak_ace", "junk"])
        self.assertEqual(len(ranges.holdings("AKs", dead={"Ah"})), 3)
        self.assertEqual(ranges.combo_of(["7s", "Ad"]), "A7o")


class SpotFilterTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in StatsTests.FIXTURES:
            add_stream(self.user, name)

    def count(self, spec):
        hands = Hand.objects.filter(PLAYED, user=self.user)
        return hands.filter(spot_filter(validate(spec), self.user, UTC)).count()

    def test_a_position_and_its_opposite(self):
        self.assertEqual(self.count(BUTTON), 5)
        self.assertEqual(self.count({"not": BUTTON}), 11)

    def test_all_and_any(self):
        self.assertEqual(self.count({"all": [BUTTON, UNOPENED]}), 3)
        self.assertEqual(self.count({"any": [BUTTON, UNOPENED]}), 9)
        self.assertEqual(self.count({"all": []}), 16)

    def test_hole_cards(self):
        self.assertEqual(self.count({"field": "hands", "value": ["KK", "AKo"]}), 3)
        self.assertEqual(self.count({"field": "range", "value": "QQ+"}), 2)
        self.assertEqual(self.count({"field": "top", "value": 5}), 5)  # QQ, KK, 88 and AKo twice
        self.assertEqual(self.count({"field": "hand_group", "value": ["premium"]}), 4)

    def test_what_the_hero_held_on_a_street(self):
        # Kings on 7-2-K, and eights on 2-8-K in the tournament.
        self.assertEqual(self.count({"field": "made", "street": "flop", "value": ["set"]}), 2)

    def test_the_heros_line(self):
        self.assertEqual(self.count({"field": "line", "street": "flop", "first": "bet", "role": "raised"}), 3)
        # Every river the hero saw, all-ins whose board ran out among them.
        self.assertEqual(self.count({"field": "line", "street": "river"}), 7)

    def test_bet_sizes_made_and_faced(self):
        self.assertEqual(self.count({"field": "bet_size", "street": "river", "min": 0.75}), 1)
        self.assertEqual(self.count({"field": "faced_size", "street": "flop", "min": 0.9}), 2)

    def test_a_sizing_flag(self):
        self.assertEqual(self.count({"field": "sizing_flag", "value": ["small_on_wet"]}), 1)

    def test_the_hands_with_an_opponent(self):
        self.assertEqual(self.count({"field": "opponent", "value": ["Judy"]}), 4)
        self.assertEqual(self.count({"field": "opponent", "value": ["Judy", "Heidi"]}), 4)

    def test_opponents_by_label(self):
        Opponent.objects.filter(user=self.user, name="Heidi").update(manual_label="station")

        self.assertEqual(self.count({"field": "opponent_label", "value": ["station"]}), 2)

    def test_a_statistic_a_result_and_a_leak(self):
        self.assertEqual(self.count({"field": "stat", "value": "vpip", "did": True}), 12)
        self.assertEqual(self.count({"field": "result", "value": "won"}), 5)
        self.assertEqual(self.count({"field": "leak", "value": "open_limp"}), 2)

    def test_tags_and_the_game(self):
        self.assertEqual(self.count({"field": "tag", "value": "position:BTN"}), 5)
        self.assertEqual(self.count({"field": "format", "value": ["tournament"]}), 1)
        self.assertEqual(self.count({"field": "game", "value": ["Omaha Pot Limit"]}), 1)

    def test_amounts_in_big_blinds(self):
        self.assertEqual(self.count({"field": "net_bb", "min": 30}), 2)
        self.assertEqual(self.count({"field": "effective_bb", "max": 50}), 2)


class SpotApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in StatsTests.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def create(self, name="Button opens", spec=None):
        spec = spec or {"all": [BUTTON, UNOPENED]}
        response = self.client.post("/api/spots/", {"name": name, "spec": spec}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_saving_listing_renaming_and_deleting(self):
        spot = self.create()

        self.assertEqual([row["name"] for row in self.client.get("/api/spots/").data], ["Button opens"])
        renamed = self.client.patch(f"/api/spots/{spot['id']}/", {"name": "Steals"}, format="json")
        self.assertEqual(renamed.data["name"], "Steals")
        self.assertEqual(self.client.delete(f"/api/spots/{spot['id']}/").status_code, 204)
        self.assertEqual(Spot.objects.count(), 0)

    def test_a_bad_spec_is_refused(self):
        response = self.client.post("/api/spots/", {"name": "x", "spec": {"field": "nope"}}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("spec", response.data)

    def test_the_history_and_the_statistics_take_a_spot_or_a_spec(self):
        spot = self.create()

        listed = self.client.get("/api/hands/", {"spot": spot["id"]}).data["results"]
        counted = self.client.get("/api/stats/", {"spot": spot["id"]}).data[0]["hands"]
        spec = self.client.get("/api/stats/", {"spec": json.dumps(BUTTON)}).data[0]["hands"]

        self.assertEqual((len(listed), counted, spec), (3, 3, 5))

    def test_another_users_spot_is_refused(self):
        other = User.objects.create_user("bob")
        spot = Spot.objects.create(user=other, name="Theirs", spec={"all": []})

        response = self.client.get("/api/hands/", {"spot": spot.pk})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(f"/api/spots/{spot.pk}/").status_code, 404)

    def test_a_bad_spec_parameter(self):
        self.assertEqual(self.client.get("/api/hands/", {"spec": "{not json"}).status_code, 400)
        self.assertEqual(self.client.get("/api/stats/", {"spec": json.dumps({"field": "x"})}).status_code, 400)

    def test_the_live_count(self):
        response = self.client.post("/api/spots/count/", {"spec": {"any": [BUTTON, UNOPENED]}}, format="json")

        self.assertEqual(response.data, {"hands": 9})

    def test_sharing_and_importing_leave_opponents_behind(self):
        spot = self.create(spec={"all": [BUTTON, {"field": "opponent", "value": ["Bob"]}]})

        code = self.client.post(f"/api/spots/{spot['id']}/share/").data["share_code"]
        other = User.objects.create_user("bob")
        self.client.force_authenticate(other)
        shared = self.client.get(f"/api/spots/shared/{code}/").data
        imported = self.client.post("/api/spots/import/", {"code": code}, format="json")

        self.assertEqual(shared["spec"], {"all": [BUTTON]})
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(Spot.objects.get(user=other).spec, {"all": [BUTTON]})

    def test_sharing_twice_keeps_the_code(self):
        spot = self.create()

        first = self.client.post(f"/api/spots/{spot['id']}/share/").data["share_code"]
        second = self.client.post(f"/api/spots/{spot['id']}/share/").data["share_code"]

        self.assertEqual(first, second)

    def test_the_conditions_are_listed(self):
        fields = {row["field"] for row in self.client.get("/api/spots/fields/").data}

        self.assertTrue({"position", "range", "made", "bet_size", "opponent", "leak"} <= fields)

    def test_saved_ranges(self):
        created = self.client.post("/api/ranges/", {"name": "Early", "hands": "TT+, AQs+, AKo"}, format="json")
        bad = self.client.post("/api/ranges/", {"name": "Bad", "hands": "XX"}, format="json")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual([row["hands"] for row in self.client.get("/api/ranges/").data], ["TT+, AQs+, AKo"])

    def test_responses_match_the_schema(self):
        spot = self.create()

        self.assertEqual(set(spot), schema_properties("SavedSpot"))
        self.assertEqual(set(self.client.get("/api/spots/fields/").data[0]), schema_properties("SpotField"))
