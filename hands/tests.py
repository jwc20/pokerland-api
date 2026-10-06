import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand
from hands.store import store_hands
from hands.views import HandPagination
from pokerlandapi.tests import openapi_schema
from tracker import parsing
from tracker.models import LogStream
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
            {key: response.data[key] for key in ("max_seats", "button_seat", "ante", "total_pot", "rake", "boards")},
            {
                "max_seats": 6,
                "button_seat": 2,
                "ante": 0,
                "total_pot": 11344,
                "rake": 624,
                "boards": [["Ad", "2h", "3h", "Jc", "5c"]],
            },
        )
        self.assertEqual(
            [player["name"] for player in response.data["players"]], ["Ivan", "Carol", "Dave", "Alice", "Bob", "Erin"]
        )
        self.assertEqual(
            response.data["events"][0],
            {"type": "post", "street": "preflop", "player": "Dave", "blind": "small blind", "amount": 100},
        )

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
