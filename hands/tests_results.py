"""Kept results (hands.results): served while the user's data and the code are as they were, worked out again after
any change to either."""

import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.http import QueryDict
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient, APITestCase

from hands import results, sessions
from hands import tests as hand_tests
from hands.models import CoachPresets, DataVersion, Hand, HandNote, KeptResult, Spot
from hands.serializers import HandFilterSerializer, LeakQuerySerializer, StatsQuerySerializer
from hands.tests import add_stream
from hands.tests_spots import BUTTON
from tracker.models import LogStream

User = get_user_model()


class KeptResultTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.calls = 0

    def work(self, answer=None):
        def compute():
            self.calls += 1
            return answer if answer is not None else {"calls": self.calls}

        return compute

    def test_an_answer_is_worked_out_once_and_then_served_in_one_query(self):
        first = results.remembered(self.user.pk, "stats", {"group_by": "none"}, self.work())
        with CaptureQueriesContext(connection) as queries:
            second = results.remembered(self.user.pk, "stats", {"group_by": "none"}, self.work())

        self.assertEqual((first, second, self.calls), ({"calls": 1}, {"calls": 1}, 1))
        self.assertEqual(len(queries), 1)

    def test_a_change_to_the_users_data_has_it_worked_out_again(self):
        results.remembered(self.user.pk, "stats", {}, self.work())
        results.changed(self.user.pk)

        self.assertEqual(results.remembered(self.user.pk, "stats", {}, self.work()), {"calls": 2})

    def test_an_answer_worked_out_during_a_change_isnt_served_after_it(self):
        # The upload commits while the stats are being worked out: what they read may predate it.
        def raced():
            results.changed(self.user.pk)
            return "before the upload"

        self.assertEqual(results.remembered(self.user.pk, "stats", {}, raced), "before the upload")
        self.assertEqual(results.remembered(self.user.pk, "stats", {}, self.work("after")), "after")

    def test_a_deploy_that_changes_the_code_starts_afresh(self):
        results.remembered(self.user.pk, "stats", {}, self.work())
        with mock.patch.object(results, "CODE", "another-release"):
            self.assertEqual(results.remembered(self.user.pk, "stats", {}, self.work()), {"calls": 2})

    def test_answers_are_kept_per_user_name_and_parameters(self):
        bob = User.objects.create_user("bob")
        results.remembered(self.user.pk, "stats", {"a": 1}, self.work("alice's"))

        self.assertEqual(results.remembered(bob.pk, "stats", {"a": 1}, self.work("bob's")), "bob's")
        self.assertEqual(results.remembered(self.user.pk, "leaks", {"a": 1}, self.work("leaks")), "leaks")
        self.assertEqual(results.remembered(self.user.pk, "stats", {"a": 2}, self.work("other")), "other")
        self.assertEqual(results.remembered(self.user.pk, "stats", {"a": 1}, self.work("again")), "alice's")

    def test_query_parameters_in_any_order_are_one_answer(self):
        one = results.key_of("stats", QueryDict("tz=UTC&tag=a&tag=b"))
        two = results.key_of("stats", QueryDict("tag=b&tz=UTC&tag=a"))

        self.assertEqual(one, two)
        self.assertNotEqual(one, results.key_of("stats", QueryDict("tz=UTC&tag=a")))

    def test_a_change_clears_the_users_kept_answers_once_it_commits(self):
        results.remembered(self.user.pk, "stats", {}, self.work())
        with self.captureOnCommitCallbacks(execute=True):
            results.changed(self.user.pk)

        self.assertFalse(KeptResult.objects.filter(user=self.user).exists())
        self.assertEqual(DataVersion.objects.get(user=self.user).version, 1)

    def test_rebuilding_the_sessions_is_a_change(self):
        results.remembered(self.user.pk, "session_patterns", {}, self.work())
        sessions.rebuild(self.user.pk)

        self.assertEqual(results.remembered(self.user.pk, "session_patterns", {}, self.work()), {"calls": 2})


class InvalidationTests(APITestCase):
    """Every way the data behind a kept answer changes, through the API where there is one."""

    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.stream = add_stream(self.user, "heads_up.txt")
        self.client.force_authenticate(self.user)

    def hands(self, **params):
        response = self.client.get("/api/stats/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data[0]["hands"] if response.data else 0

    def test_an_upload(self):
        before = self.hands()
        add_stream(self.user, "steals_and_squeezes.txt")

        self.assertGreater(self.hands(), before)

    def test_notes_are_not_read_by_a_kept_answer_so_they_change_nothing(self):
        # Only the history (HandListQuerySerializer, not kept) filters by notes. A kept view that took these filters
        # would have to call results.changed when a note is written.
        for query in (HandFilterSerializer, StatsQuerySerializer, LeakQuerySerializer):
            self.assertFalse({"review", "note_tag"} & set(query().fields), query.__name__)
        hand = Hand.objects.filter(user=self.user).first()
        version = results.version_of(self.user.pk)

        self.client.post(f"/api/hands/{hand.pk}/notes/", {"kind": "tag", "tag": "tilt"}, format="json")
        self.assertEqual(results.version_of(self.user.pk), version)

    def test_a_saved_spot_edited(self):
        spot = self.client.post("/api/spots/", {"name": "Button", "spec": BUTTON}, format="json").data
        on_button = self.hands(spot=spot["id"])

        self.client.patch(f"/api/spots/{spot['id']}/", {"spec": {"not": BUTTON}}, format="json")
        self.assertEqual(self.hands(spot=spot["id"]), self.hands() - on_button)

    def test_leak_presets_and_reviews(self):
        add_stream(self.user, "steals_and_squeezes.txt")
        before = {check["key"]: check for check in self.client.get("/api/leaks/").data}

        self.client.patch("/api/leaks/presets/", {"open_bb": 9}, format="json")
        self.client.post("/api/leaks/open_size/reviewed/")
        after = {check["key"]: check for check in self.client.get("/api/leaks/").data}

        self.assertNotEqual(before["open_size"], after["open_size"])
        self.assertIsNone(before["open_size"]["reviewed"])
        self.assertIsNotNone(after["open_size"]["reviewed"])

    def test_a_hand_saved_on_its_own_as_the_admin_does(self):
        hand = Hand.objects.filter(user=self.user).first()
        since = hand.played_at.date().isoformat()
        before = self.hands(since=since)

        hand.played_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        hand.save()
        self.assertEqual(self.hands(since=since), before - 1)

    def test_a_stream_deleted_with_its_hands(self):
        self.assertGreater(self.hands(), 0)
        self.stream.delete()

        self.assertEqual(self.hands(), 0)

    def test_deleting_a_user_with_notes_presets_and_spots(self):
        hand = Hand.objects.filter(user=self.user).first()
        HandNote.objects.create(user=self.user, hand=hand, kind="tag", value="tilt")
        CoachPresets.objects.create(user=self.user)
        Spot.objects.create(user=self.user, name="Button", spec=BUTTON)
        self.hands()

        self.user.delete()  # their kept answers go with them, and no version is moved on for a user being deleted
        self.assertFalse(KeptResult.objects.exists())
        self.assertFalse(DataVersion.objects.exists())
        self.assertFalse(LogStream.objects.exists())


class KeptResponseTests(APITestCase):
    """The views that keep their answers serve the same bytes kept as fresh, and read no hands a second time."""

    URLS = (
        "/api/stats/",
        "/api/stats/?group_by=position&tz=UTC",
        "/api/hands/tags/",
        "/api/leaks/",
        "/api/leaks/?group=postflop",
        "/api/sessions/patterns/",
        "/api/stats/sizing/",
        "/api/stats/lines/",
    )

    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in hand_tests.StatsTests.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def test_kept_and_fresh_are_alike_and_a_kept_one_is_one_query(self):
        for url in self.URLS:
            with self.subTest(url=url):
                fresh = self.client.get(url)
                with CaptureQueriesContext(connection) as queries:
                    kept = self.client.get(url)

                self.assertEqual(fresh.status_code, 200, fresh.data)
                self.assertEqual(kept.content, fresh.content)
                self.assertFalse([query["sql"] for query in queries if "hands_hand" in query["sql"]])

    def test_bad_parameters_are_refused_not_kept(self):
        self.assertEqual(self.client.get("/api/stats/?group_by=nonsense").status_code, 400)
        self.assertFalse(KeptResult.objects.exists())

    def test_one_users_answers_are_never_anothers(self):
        bob = APIClient()
        bob.force_authenticate(User.objects.create_user("bob"))
        mine = self.client.get("/api/stats/").data

        self.assertNotEqual(bob.get("/api/stats/").data, mine)
