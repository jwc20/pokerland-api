"""Query counts: listing more rows mustn't cost more queries. Each test counts a list's queries, adds rows, and counts
again; a query per row (N+1) shows as a difference."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandNote
from hands.tests import add_stream
from hands.tests_spots import BUTTON
from leagues.models import Membership
from practice import sets
from practice.models import RuleProgress

User = get_user_model()
FIXTURES = ("heads_up.txt", "steals_and_squeezes.txt", "side_pots.txt", "tournament.txt", "zoom_usd.txt")


class QueryCountTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def count(self, url, params=None, client=None):
        with CaptureQueriesContext(connection) as captured:
            response = (client or self.client).get(url, params or {})
        self.assertEqual(response.status_code, 200, getattr(response, "data", response))
        return len(captured)

    def assertFlat(self, url, grow, params=None, client=None):
        """`url` costs as many queries after `grow()` adds rows to it as before."""
        before = self.count(url, params, client)
        grow()
        self.assertEqual(self.count(url, params, client), before, f"{url}: a query per row")

    def post(self, url, data, client=None):
        response = (client or self.client).post(url, data, format="json")
        self.assertIn(response.status_code, (200, 201), response.data)
        return response.data


class HandListTests(QueryCountTestCase):
    def test_pages_of_hands_sessions_opponents_and_tournaments(self):
        for url in ("/api/hands/", "/api/sessions/", "/api/opponents/", "/api/tournaments/"):
            with self.subTest(url=url):
                self.assertEqual(self.count(url, {"page_size": 1}), self.count(url, {"page_size": 50}), url)

    def test_a_hand_and_its_notes(self):
        hand = Hand.objects.filter(user=self.user).first()

        def note(n):
            return lambda: [
                HandNote.objects.create(user=self.user, hand=hand, kind="tag", value=f"tag{n}-{i}") for i in range(3)
            ]

        self.assertFlat(f"/api/hands/{hand.pk}/notes/", note(1))
        def flag():
            for other in Hand.objects.filter(user=self.user)[:6]:
                HandNote.objects.update_or_create(
                    user=self.user, hand=other, kind="review", defaults={"value": "to_review"}
                )

        self.assertFlat("/api/review/", flag)

    def test_spots_ranges_and_shares(self):
        hands = list(Hand.objects.filter(user=self.user)[:4])
        self.assertFlat("/api/spots/", lambda: [
            self.post("/api/spots/", {"name": f"Spot {i}", "spec": BUTTON}) for i in range(3)
        ])
        self.assertFlat("/api/ranges/", lambda: [
            self.post("/api/ranges/", {"name": f"Range {i}", "hands": "TT+, AQs+"}) for i in range(3)
        ])
        self.assertFlat("/api/shares/", lambda: [self.post("/api/shares/", {"hand": hand.pk}) for hand in hands])


@override_settings(CLASSES_ENABLED=True)  # a playbook's classes are part of the list
class PracticeListTests(QueryCountTestCase):
    def test_playbooks_of_your_own_assigned_to_classes(self):
        house = sets.house_playbook()
        league = self.post("/api/leagues/", {"name": "Tuesday"})

        def own(n):
            def grow():
                for i in range(n):
                    copy = self.post("/api/practice/playbooks/", {"copy_of": house.pk, "name": f"Mine {n}-{i}"})
                    self.post(f"/api/leagues/{league['id']}/assignments/", {"kind": "playbook", "playbook": copy["id"]})

            return grow

        own(1)()
        self.assertFlat("/api/practice/playbooks/", own(3))

    def test_matches_tables_and_tests(self):
        self.assertFlat("/api/practice/matches/", lambda: [self.post("/api/practice/matches/", {}) for _ in range(2)])
        self.assertFlat("/api/practice/tables/", lambda: [
            self.post("/api/practice/tables/", {"seats": 2}) for _ in range(2)
        ])
        self.assertFlat("/api/practice/tests/", lambda: [
            self.post("/api/practice/tests/", {"tz": "UTC"}) for _ in range(2)
        ])

    def test_a_set_of_your_own_hands_and_how_each_ended(self):
        practice_set = self.post("/api/practice/sets/", {"kind": "my_hands", "tz": "UTC"})
        self.assertGreaterEqual(len(practice_set["spots"]), 4)

        def answer():
            for spot in practice_set["spots"][:4]:
                body = {"scenario": spot["scenario"]["id"], "set": practice_set["id"], "action": "fold", "tz": "UTC"}
                if spot["scenario"]["spec"]["legal"]["can_check"]:
                    body["action"] = "check"
                self.post("/api/practice/attempts/", body)

        self.assertFlat(f"/api/practice/sets/{practice_set['id']}/", answer)

    def test_a_set_and_its_answers(self):
        practice_set = self.post("/api/practice/sets/", {"kind": "library", "tz": "UTC"})

        def answer():
            for spot in practice_set["spots"][:4]:
                question = spot["scenario"]["spec"]["question"]
                body = {"scenario": spot["scenario"]["id"], "set": practice_set["id"], "tz": "UTC"}
                if question["kind"] == "choice":
                    body["choice"] = 0
                elif question["kind"] == "range":
                    body["hand_range"] = "AA"
                else:
                    body["action"] = "fold"
                self.post("/api/practice/attempts/", body)

        self.assertFlat(f"/api/practice/sets/{practice_set['id']}/", answer)


@override_settings(CLASSES_ENABLED=True)
class LeagueListTests(QueryCountTestCase):
    def member(self, name, league):
        user = User.objects.create_user(name)
        client = APIClient()
        client.force_authenticate(user)
        self.post("/api/leagues/join/", {"code": league["invite_code"]}, client)
        return user, client

    def test_classes_and_a_class(self):
        league = self.post("/api/leagues/", {"name": "Tuesday"})
        hands = list(Hand.objects.filter(user=self.user)[:4])

        self.assertFlat("/api/leagues/", lambda: [self.post("/api/leagues/", {"name": f"Class {i}"}) for i in range(3)])

        def grow():
            for i in range(3):
                self.member(f"student{i}", league)
            for hand in hands:
                self.post(f"/api/leagues/{league['id']}/assignments/", {"kind": "hand", "hand": hand.pk})

        self.assertFlat(f"/api/leagues/{league['id']}/", grow)

    def test_the_progress_of_members_who_share_it(self):
        league = self.post("/api/leagues/", {"name": "Tuesday"})
        playbook = self.post("/api/practice/playbooks/", {"copy_of": sets.house_playbook().pk, "name": "Mine"})
        self.post(f"/api/leagues/{league['id']}/assignments/", {"kind": "playbook", "playbook": playbook["id"]})

        def sharing(names):
            def grow():
                for name in names:
                    user, client = self.member(name, league)
                    client.patch(f"/api/leagues/{league['id']}/me/", {"shares_progress": True}, format="json")
                    RuleProgress.objects.create(user=user, playbook_key=playbook["key"], family="sizing", stage=2)

            return grow

        sharing(["one"])()
        self.assertFlat(f"/api/leagues/{league['id']}/progress/", sharing(["two", "three", "four"]))
        self.assertEqual(Membership.objects.filter(league_id=league["id"], shares_progress=True).count(), 4)
