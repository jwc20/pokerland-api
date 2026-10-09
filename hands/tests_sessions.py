import copy
import datetime
import uuid
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandNote, Session
from hands.store import store_hands
from hands.tests import schema_properties
from tracker import parsing
from tracker.models import LogStream
from tracker.tests_parsing import fixture

User = get_user_model()
T0 = datetime.datetime(2026, 10, 2, 18, 0, tzinfo=datetime.UTC)


def minutes(*offsets):
    return [T0 + datetime.timedelta(minutes=offset) for offset in offsets]


class SessionTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.stream = LogStream.objects.create(
            user=self.user,
            stream_id=uuid.uuid4(),
            source="pokerstars",
            platform="macos",
            client_version="0.1.0",
            fingerprint="0" * 64,
        )
        _, self.templates = parsing.parse(fixture("play_money.txt"), {})
        self.count = 0
        self.client.force_authenticate(self.user)

    def play(self, times, table="Table A"):
        """Stores a hand at each of `times` at `table`, copies of the fixture's, numbered afresh."""
        hands = []
        for when in times:
            hand = copy.deepcopy(self.templates[self.count % len(self.templates)])
            self.count += 1
            hand.update(hand_id=f"9{self.count:06d}", played_at=when, table=table)
            hands.append(hand)
        store_hands(self.stream, hands)
        return hands

    def sessions(self):
        return list(Session.objects.order_by("start"))


class SessionBuildTests(SessionTestCase):
    def test_a_gap_of_over_half_an_hour_starts_a_session(self):
        self.play(minutes(0, 10, 40, 71, 101))

        self.assertEqual([session.hands for session in self.sessions()], [3, 2])

    def test_a_session_that_carries_on_keeps_its_row(self):
        self.play(minutes(0, 10))
        [first] = self.sessions()

        self.play(minutes(25))

        [after] = self.sessions()
        self.assertEqual((after.pk, after.hands, after.end), (first.pk, 3, minutes(25)[0]))

    def test_a_hand_in_the_gap_joins_two_sessions(self):
        self.play(minutes(0, 50))
        self.assertEqual(len(self.sessions()), 2)

        self.play(minutes(25))

        [joined] = self.sessions()
        self.assertEqual((joined.hands, joined.start, joined.end), (3, T0, minutes(50)[0]))
        self.assertEqual(Hand.objects.filter(session=joined).count(), 3)

    def test_tables_played_at_once(self):
        self.play(minutes(0, 10, 20), table="Table A")
        self.play(minutes(15, 30), table="Table B")

        [session] = self.sessions()
        open_at = dict(Hand.objects.order_by("played_at").values_list("played_at", "tables_open"))

        self.assertEqual((session.tables, session.most_tables), (2, 2))
        self.assertEqual([open_at[when] for when in minutes(0, 10, 15, 20, 30)], [1, 1, 2, 2, 1])

    def test_hours_into_the_session(self):
        self.play(minutes(0, 25, 50, 75, 100, 125, 150, 175, 200))

        hours = list(Hand.objects.order_by("played_at").values_list("session_hour", flat=True))

        self.assertEqual(hours, [0, 0, 0, 1, 1, 2, 2, 2, 3])

    def test_the_sessions_counts(self):
        hands = self.play(minutes(0, 5, 10))

        [session] = self.sessions()
        net = [hand["hero_net"] / hand["big_blind"] for hand in hands]

        self.assertAlmostEqual(session.net_bb, sum(net))
        self.assertAlmostEqual(session.net_bb_squares, sum(bb * bb for bb in net))
        self.assertEqual(session.ev_net_bb, session.net_bb)  # no all-ins
        self.assertEqual(session.biggest_pot_bb, max(hand["total_pot"] / hand["big_blind"] for hand in hands))

    def test_a_reparse_leaves_the_sessions_as_they_were(self):
        hands = self.play(minutes(0, 10, 50))
        before = [(session.pk, session.hands) for session in self.sessions()]

        store_hands(self.stream, hands)

        self.assertEqual([(session.pk, session.hands) for session in self.sessions()], before)

    def test_rebuilding_every_session(self):
        self.play(minutes(0, 10, 50))
        Session.objects.all().delete()
        out = StringIO()

        call_command("rebuild_sessions", stdout=out)

        self.assertEqual([session.hands for session in self.sessions()], [2, 1])
        self.assertIn("alice: 2 sessions", out.getvalue())


class SessionApiTests(SessionTestCase):
    def test_the_list_latest_first_with_notes_counted(self):
        hands = self.play(minutes(0, 10, 50, 55))
        flagged = Hand.objects.get(hand_id=hands[0]["hand_id"])
        HandNote.objects.create(user=self.user, hand=flagged, kind="review", value="to_review")
        HandNote.objects.create(user=self.user, hand=flagged, kind="tag", value="tilt")

        rows = self.client.get("/api/sessions/").data["results"]

        self.assertEqual([row["hands"] for row in rows], [2, 2])
        self.assertEqual([(row["flagged"], row["noted"], row["minutes"]) for row in rows], [(0, 0, 5), (1, 1, 10)])

    def test_the_list_narrows_to_days_in_a_time_zone(self):
        self.play(minutes(0))
        self.play(minutes(60 * 24))

        def since_the_3rd(tz):
            return len(self.client.get("/api/sessions/", {"since": "2026-10-03", "tz": tz}).data["results"])

        # 18:00 UTC on the 2nd is already 3:00 on the 3rd in Seoul.
        self.assertEqual((since_the_3rd("UTC"), since_the_3rd("Asia/Seoul")), (1, 2))

    def test_a_sessions_hands(self):
        self.play(minutes(0, 10, 50))
        first = self.sessions()[0]

        response = self.client.get("/api/hands/", {"session": first.pk})

        self.assertEqual(len(response.data["results"]), 2)

    def test_the_days_list_their_sessions(self):
        self.play(minutes(0, 50))

        [day] = self.client.get("/api/hands/days/", {"tz": "UTC"}).data["days"]

        self.assertEqual([session["hands"] for session in day["sessions"]], [1, 1])

    def test_patterns_by_hour_time_of_day_weekday_and_tables(self):
        self.play(minutes(0, 25, 50, 75))

        found = self.client.get("/api/sessions/patterns/", {"tz": "UTC"}).data

        self.assertEqual([(group["key"], group["hands"]) for group in found["hours_in"]], [("0", 3), ("1", 1)])
        self.assertEqual([group["key"] for group in found["time_of_day"]], ["evening"])
        self.assertEqual([group["key"] for group in found["weekday"]], ["5"])  # a Friday
        self.assertEqual([group["key"] for group in found["tables"]], ["1"])

    def test_other_users_sessions_are_out_of_reach(self):
        self.play(minutes(0))
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        self.assertEqual(client.get("/api/sessions/").data["results"], [])
        self.assertEqual(client.get(f"/api/sessions/{self.sessions()[0].pk}/").status_code, 404)
        self.assertEqual(APIClient().get("/api/sessions/").status_code, 401)

    def test_responses_match_the_schema(self):
        self.play(minutes(0, 10))

        row = self.client.get("/api/sessions/").data["results"][0]
        found = self.client.get("/api/sessions/patterns/").data

        self.assertEqual(set(row), schema_properties("Session"))
        self.assertEqual(set(found), schema_properties("SessionPatterns"))
        self.assertEqual(set(found["hours_in"][0]), schema_properties("SessionGroup"))
