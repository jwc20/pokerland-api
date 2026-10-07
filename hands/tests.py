import datetime
import statistics
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from pokerkit import HandHistory
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandPlayer
from hands.stats import proportion, streaks
from hands.store import store_hands
from hands.views import HandPagination
from pokerlandapi.tests import openapi_schema
from tracker import parsing
from tracker.models import LogStream
from tracker.parsing.facts import STATS
from tracker.tests_parsing import fixture

User = get_user_model()


def add_stream(user, fixture_name):
    """A stream of `user` holding the hands of a fixture file, as a drain would have saved them."""
    stream = LogStream.objects.create(
        user=user,
        stream_id=uuid.uuid4(),
        source="pokerstars",
        platform="macos",
        client_version="0.1.0",
        fingerprint="0" * 64,
    )
    _, hands = parsing.parse(fixture(fixture_name), {})
    store_hands(stream, hands)
    return stream


def schema_properties(component):
    return set(openapi_schema()["components"]["schemas"][component]["properties"])


class HandTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "play_money.txt")
        self.client.force_authenticate(self.user)

    def test_the_history_lists_the_users_hands_most_recent_first(self):
        response = self.client.get("/api/hands/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [hand["hand_id"] for hand in response.data["results"]],
            ["262289826745", "262289822697", "262289818894", "262289811345", "262289806991"],
        )
        self.assertEqual(
            {key: response.data["results"][-1][key] for key in ("hero", "hero_position", "hero_cards", "hero_net")},
            {"hero": "Alice", "hero_position": "UTG", "hero_cards": ["Jc", "5c"], "hero_net": -600},
        )

    def test_the_history_pages_with_a_cursor(self):
        seen = []
        with mock.patch.object(HandPagination, "page_size", 2):
            url = "/api/hands/"
            while url:
                response = self.client.get(url)
                seen += [hand["hand_id"] for hand in response.data["results"]]
                url = response.data["next"]

        self.assertEqual(len(seen), 5)
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_a_hand_has_what_its_replay_needs(self):
        hand = Hand.objects.get(hand_id="262289811345")

        response = self.client.get(f"/api/hands/{hand.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {key: response.data[key] for key in ("max_seats", "button_seat", "ante", "total_pot", "rake", "board")},
            {
                "max_seats": 6,
                "button_seat": 2,
                "ante": 0,
                "total_pot": 11344,
                "rake": 624,
                "board": ["Ad", "2h", "3h", "Jc", "5c"],
            },
        )
        self.assertEqual(
            [player["name"] for player in response.data["players"]], ["Ivan", "Carol", "Dave", "Alice", "Bob", "Erin"]
        )
        self.assertEqual(
            response.data["events"][0],
            {
                "type": "post",
                "street": "preflop",
                "player": "Ivan",
                "blind": "dead small blind",
                "amount": 100,
                "dead": 100,
            },
        )
        self.assertEqual(HandHistory.loads(response.data["phh"]).hand, 262289811345)

    def test_the_history_narrows_to_a_tag(self):
        response = self.client.get("/api/hands/", {"tag": "position:UTG"})

        self.assertEqual([hand["hand_id"] for hand in response.data["results"]], ["262289826745", "262289806991"])

    def test_the_history_narrows_to_a_day_in_a_time_zone(self):
        def count(day, tz):
            return len(self.client.get("/api/hands/", {"date": day, "tz": tz}).data["results"])

        self.assertEqual(count("2026-10-04", "UTC"), 5)
        self.assertEqual(count("2026-10-03", "America/New_York"), 5)
        self.assertEqual(count("2026-10-04", "America/New_York"), 0)

    def test_a_smaller_page_keeps_the_filters_in_its_next_link(self):
        first = self.client.get("/api/hands/", {"tag": "position:UTG", "page_size": 1}).data
        second = self.client.get(first["next"]).data

        self.assertEqual(
            [hand["hand_id"] for hand in first["results"] + second["results"]], ["262289826745", "262289806991"]
        )
        self.assertIsNone(second["next"])

    def test_unknown_filters_are_rejected(self):
        for params in (
            {"tag": "colour:red"},
            {"tag": "position:"},
            {"tag": "stakes:USD:5"},
            {"tag": "format:ring"},
            {"date": "2026-13-01"},
            {"date": "2026-10-04", "tz": "Mars/Olympus_Mons"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/api/hands/", params).status_code, 400)

    def test_responses_match_the_schema(self):
        listed = self.client.get("/api/hands/").data
        detail = self.client.get(f"/api/hands/{listed['results'][0]['id']}/").data

        self.assertEqual(set(listed), schema_properties("PaginatedHandSummaryList"))
        self.assertEqual(set(listed["results"][0]), schema_properties("HandSummary"))
        self.assertEqual(set(detail), schema_properties("HandDetail"))
        self.assertEqual(set(detail["players"][0]), schema_properties("HandPlayer"))
        for event in detail["events"]:
            self.assertLessEqual(set(event), schema_properties("HandEvent"))

    def test_other_users_hands_are_hidden(self):
        bob = User.objects.create_user("bob")
        client = APIClient()
        client.force_authenticate(bob)
        hand = Hand.objects.first()

        self.assertEqual(client.get("/api/hands/").data["results"], [])
        self.assertEqual(client.get(f"/api/hands/{hand.pk}/").status_code, 404)

    def test_hands_need_a_signed_in_user(self):
        self.assertEqual(APIClient().get("/api/hands/").status_code, 401)

    def test_storing_a_hand_again_updates_it_in_place(self):
        hand = Hand.objects.get(hand_id="262289806991")
        _, parsed = parsing.parse(fixture("play_money.txt"), {})
        parsed[0]["hero_net"] = 1

        store_hands(hand.stream, parsed)

        self.assertEqual(Hand.objects.count(), 5)
        self.assertEqual(Hand.objects.get(pk=hand.pk).hero_net, 1)

    def test_the_same_hand_is_kept_per_user(self):
        add_stream(User.objects.create_user("bob"), "play_money.txt")

        self.assertEqual(Hand.objects.filter(hand_id="262289806991").count(), 2)


class StreakTests(SimpleTestCase):
    today = datetime.date(2026, 10, 6)

    def days_ago(self, *offsets):
        return sorted(self.today - datetime.timedelta(days=offset) for offset in offsets)

    def test_no_days_are_no_streak(self):
        self.assertEqual(streaks([], self.today), (0, 0))

    def test_a_streak_runs_up_to_today(self):
        self.assertEqual(streaks(self.days_ago(2, 1, 0), self.today), (3, 3))

    def test_a_streak_lasts_until_the_day_is_out(self):
        self.assertEqual(streaks(self.days_ago(2, 1), self.today), (2, 2))

    def test_a_day_without_hands_ends_a_streak(self):
        self.assertEqual(streaks(self.days_ago(3, 2), self.today), (0, 2))

    def test_the_best_streak_can_be_an_earlier_one(self):
        self.assertEqual(streaks(self.days_ago(9, 8, 7, 6, 1, 0), self.today), (2, 4))


def at(*args):
    return datetime.datetime(*args, tzinfo=datetime.UTC)


class HandDaysTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "play_money.txt")  # five hands from 01:53 to 01:57 UTC on 2026-10-04
        self.client.force_authenticate(self.user)

    def days(self, tz):
        return self.client.get("/api/hands/days/", {"tz": tz}).data

    def test_days_begin_and_end_in_the_time_zone_asked_for(self):
        new_york = self.days("America/New_York")["days"]

        self.assertEqual([(day["date"], day["hands"]) for day in self.days("UTC")["days"]], [("2026-10-04", 5)])
        self.assertEqual([(day["date"], day["hands"]) for day in new_york], [("2026-10-03", 5)])
        self.assertAlmostEqual(new_york[0]["net_bb"], (-600 - 200 - 400 - 2659 - 4200) / 200, delta=0.01)

    def test_a_late_hand_counts_for_the_next_day_further_east(self):
        Hand.objects.filter(hand_id="262289826745").update(played_at=at(2026, 10, 4, 23, 30))

        days = self.days("Asia/Tokyo")["days"]

        self.assertEqual([(day["date"], day["hands"]) for day in days], [("2026-10-04", 4), ("2026-10-05", 1)])

    def test_the_day_the_clocks_go_back_has_25_hours(self):
        # In New York, 2026-11-01 runs from 04:00 UTC to 05:00 UTC the next day.
        for hand, played_at in zip(
            Hand.objects.order_by("hand_id"), (at(2026, 11, 1, 4), at(2026, 11, 2, 4, 59), at(2026, 11, 2, 5))
        ):
            Hand.objects.filter(pk=hand.pk).update(played_at=played_at)

        days = self.days("America/New_York")["days"]
        listed = self.client.get("/api/hands/", {"date": "2026-11-01", "tz": "America/New_York"}).data["results"]

        self.assertEqual(
            [(day["date"], day["hands"]) for day in days], [("2026-10-03", 2), ("2026-11-01", 2), ("2026-11-02", 1)]
        )
        self.assertEqual(len(listed), 2)

    def test_the_streak_runs_until_a_day_without_hands_is_out(self):
        Hand.objects.filter(hand_id="262289826745").update(played_at=at(2026, 10, 5, 12))

        def streak_on(now):
            with mock.patch("django.utils.timezone.now", return_value=now):
                calendar = self.days("UTC")
            return calendar["current_streak"], calendar["best_streak"], calendar["played_today"]

        self.assertEqual(streak_on(at(2026, 10, 5, 20)), (2, 2, True))
        self.assertEqual(streak_on(at(2026, 10, 6, 20)), (2, 2, False))
        self.assertEqual(streak_on(at(2026, 10, 7, 0, 1)), (0, 2, False))

    def test_days_need_a_known_time_zone(self):
        for tz in (None, "", "Mars/Olympus_Mons", "utc", "A" * 300):
            with self.subTest(tz=tz):
                response = self.client.get("/api/hands/days/", {} if tz is None else {"tz": tz})
                self.assertEqual(response.status_code, 400)

    def test_other_users_hands_are_not_counted(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        self.assertEqual(client.get("/api/hands/days/", {"tz": "UTC"}).data["days"], [])
        self.assertEqual(client.get("/api/hands/tags/").data[0]["hands"], 0)

    def test_days_and_tags_need_a_signed_in_user(self):
        self.assertEqual(APIClient().get("/api/hands/days/", {"tz": "UTC"}).status_code, 401)
        self.assertEqual(APIClient().get("/api/hands/tags/").status_code, 401)

    def test_responses_match_the_schema(self):
        calendar = self.days("UTC")
        tags = self.client.get("/api/hands/tags/").data

        self.assertEqual(set(calendar), schema_properties("HandCalendar"))
        self.assertEqual(set(calendar["days"][0]), schema_properties("HandDay"))
        for tag in tags:
            self.assertEqual(set(tag), schema_properties("HandTag"))
        stakes = next(tag["stakes"] for tag in tags if tag["group"] == "stakes")
        self.assertEqual(set(stakes), schema_properties("TagStakes"))


class HandTagTests(APITestCase):
    FIXTURES = (
        "heads_up.txt",
        "omaha_eur.txt",
        "play_money.txt",
        "side_pots.txt",
        "split_pots.txt",
        "tournament.txt",
        "zoom_usd.txt",
    )

    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in self.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def tags(self):
        return {tag["key"]: tag for tag in self.client.get("/api/hands/tags/").data}

    def test_hands_are_counted_by_position_game_cash_stakes_and_format(self):
        tags = self.tags()

        self.assertEqual(tags["all"]["hands"], 14)
        self.assertEqual(
            {key: tags[key]["hands"] for key in ("position:BTN", "game:Omaha Pot Limit", "stakes::100:200")},
            {"position:BTN": 4, "game:Omaha Pot Limit": 1, "stakes::100:200": 10},
        )
        self.assertEqual(tags["stakes:EUR:2:5"]["stakes"], {"currency": "EUR", "small_blind": 2, "big_blind": 5})
        self.assertIsNone(tags["position:BTN"]["stakes"])

    def test_only_cash_games_have_stakes(self):
        stakes = {key for key in self.tags() if key.startswith("stakes:")}

        self.assertEqual(stakes, {"stakes::10:20", "stakes::100:200", "stakes:EUR:2:5", "stakes:USD:5:10"})

    def test_every_hand_has_one_format(self):
        tags = self.tags()

        self.assertEqual(
            {key: tag["hands"] for key, tag in tags.items() if tag["group"] == "format"},
            {"format:play_money": 11, "format:cash": 2, "format:tournament": 1},
        )

    def test_a_tag_counts_won_and_lost_hands_and_the_net_in_big_blinds(self):
        button = self.tags()["position:BTN"]

        self.assertEqual((button["hands"], button["won"], button["lost"]), (4, 1, 3))
        self.assertAlmostEqual(button["net_bb"], -10 / 20 - 2659 / 200 - 10000 / 200 + 2130 / 50, delta=0.01)

    def test_a_tag_has_the_spread_of_its_results_in_big_blinds(self):
        tags = self.tags()

        self.assertAlmostEqual(
            tags["position:BTN"]["bb_stdev"],
            statistics.stdev([-10 / 20, -2659 / 200, -10000 / 200, 2130 / 50]),
            delta=0.01,
        )
        self.assertIsNone(tags["game:Omaha Pot Limit"]["bb_stdev"])  # one hand has no spread

    def test_all_comes_first_then_the_most_played_tags(self):
        tags = self.client.get("/api/hands/tags/").data
        counts = [tag["hands"] for tag in tags[1:]]

        self.assertEqual(tags[0]["key"], "all")
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_each_tag_lists_the_hands_it_counts(self):
        for tag in self.client.get("/api/hands/tags/").data:
            with self.subTest(tag=tag["key"]):
                listed = self.client.get("/api/hands/", {"tag": tag["key"]}).data["results"]
                self.assertEqual(len(listed), tag["hands"])
                self.assertEqual(sum(hand["hero_net"] > 0 for hand in listed), tag["won"])

    def test_hands_the_user_sat_out_are_left_out(self):
        Hand.objects.filter(hand_id="219396263497").update(hero="", hero_position="", hero_cards=[], hero_net=0)

        self.assertEqual(self.tags()["all"]["hands"], 13)
        self.assertEqual(len(self.client.get("/api/hands/", {"tag": "all"}).data["results"]), 13)
        self.assertEqual(len(self.client.get("/api/hands/").data["results"]), 14)


class HandPlayerTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.stream = add_stream(self.user, "steals_and_squeezes.txt")

    def test_each_player_in_a_hand_has_a_row(self):
        hand = Hand.objects.get(hand_id="262300000002")

        hero = hand.seats.get(is_hero=True)

        self.assertEqual(hand.seats.count(), 6)
        self.assertEqual((hero.name, hero.position, hero.squeeze_could, hero.squeeze_did), ("Alice", "BTN", 1, 1))
        self.assertEqual((hand.hero_combo, hand.pot_type, hand.hero_situation), ("KK", "3bet", "raised"))
        self.assertEqual(hand.facts["hero"]["made"], {"flop": "set"})

    def test_storing_hands_again_replaces_their_rows(self):
        first = set(HandPlayer.objects.values_list("id", flat=True))
        _, hands = parsing.parse(fixture("steals_and_squeezes.txt"), {})

        store_hands(self.stream, hands)

        self.assertEqual(HandPlayer.objects.filter(user=self.user).count(), 12)
        self.assertFalse(first & set(HandPlayer.objects.values_list("id", flat=True)))

    def test_every_statistic_has_its_columns(self):
        columns = {field.name for field in HandPlayer._meta.get_fields()}

        for stat in STATS:
            with self.subTest(stat=stat):
                self.assertLessEqual({f"{stat}_could", f"{stat}_did"}, columns)


class ProportionTests(SimpleTestCase):
    def test_a_share_with_its_wilson_interval(self):
        self.assertEqual(proportion(5, 10), {"did": 5, "could": 10, "pct": 50.0, "ci_low": 23.7, "ci_high": 76.3})
        self.assertEqual((proportion(0, 10)["ci_low"], proportion(0, 10)["ci_high"]), (0.0, 27.8))
        self.assertEqual((proportion(10, 10)["ci_low"], proportion(10, 10)["ci_high"]), (72.2, 100.0))

    def test_no_chances_have_no_share(self):
        self.assertEqual(proportion(0, 0), {"did": 0, "could": 0, "pct": None, "ci_low": None, "ci_high": None})


class StatsTests(APITestCase):
    FIXTURES = (*HandTagTests.FIXTURES, "steals_and_squeezes.txt")

    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in self.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def stats(self, **params):
        response = self.client.get("/api/stats/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_all_the_heros_hands(self):
        [group] = self.stats()

        counts = {stat: (group["stats"][stat]["did"], group["stats"][stat]["could"]) for stat in ("vpip", "pfr", "rfi")}

        self.assertEqual((group["key"], group["hands"]), ("all", 16))
        self.assertEqual(counts, {"vpip": (12, 16), "pfr": (7, 16), "rfi": (2, 7)})
        self.assertEqual(group["stats"]["vpip"], proportion(12, 16))
        self.assertEqual((group["stats"]["aggression"]["did"], group["stats"]["aggression"]["could"]), (10, 18))

    def test_by_position_in_the_order_they_act(self):
        groups = self.stats(group_by="position")

        self.assertEqual(
            [(group["key"], group["hands"], group["net_bb"]) for group in groups],
            [("UTG", 3, -28.5), ("CO", 1, -1.0), ("BTN", 5, -50.2), ("SB", 3, -79.3), ("BB", 4, 56.89)],
        )
        self.assertEqual(groups[2]["stats"]["rfi"]["did"], 2)

    def test_by_month(self):
        groups = self.stats(group_by="month", tz="UTC")

        self.assertEqual([(group["key"], group["hands"]) for group in groups], [("2020-09", 4), ("2026-10", 12)])

    def test_a_tags_hands_or_a_stretch_of_days(self):
        self.assertEqual(self.stats(tag="format:tournament")[0]["hands"], 1)
        self.assertEqual(self.stats(since="2026-10-01")[0]["hands"], 12)
        self.assertEqual(self.stats(until="2020-09-30", tz="America/New_York")[0]["hands"], 4)

    def test_the_spread_of_the_results(self):
        [group] = self.stats(tag="position:BTN")

        results = Hand.objects.filter(hero_position="BTN").values_list("hero_net", "big_blind")

        self.assertAlmostEqual(group["bb_stdev"], statistics.stdev(net / bb for net, bb in results), delta=0.01)

    def test_bad_filters_are_rejected(self):
        for params in ({"group_by": "table"}, {"tag": "nope"}, {"since": "2026-10-02", "until": "2026-10-01"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/api/stats/", params).status_code, 400)

    def test_another_users_hands_are_not_counted(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        [group] = client.get("/api/stats/").data

        self.assertEqual((group["hands"], group["stats"]["vpip"]["could"], group["bb_stdev"]), (0, 0, None))

    def test_stats_need_a_signed_in_user(self):
        self.assertEqual(APIClient().get("/api/stats/").status_code, 401)

    def test_responses_match_the_schema(self):
        [group] = self.stats()

        self.assertEqual(set(group), schema_properties("StatGroup"))
        self.assertEqual(set(group["stats"]), schema_properties("StatSet"))
        self.assertEqual(set(group["stats"]["vpip"]), schema_properties("Stat"))
