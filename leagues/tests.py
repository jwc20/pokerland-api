"""Classes: coaches, members and invite codes; playbooks and hands put before a class; what coaches see of members."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandShare
from hands.tests import add_stream
from leagues.models import Assignment, League, Membership
from practice.models import Scenario
from practice.tests import NOW

User = get_user_model()


@override_settings(CLASSES_ENABLED=True)  # not open yet; these test them as they will be
class ClassTestCase(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.coach = User.objects.create_user("coach")
        self.alice = User.objects.create_user("alice")
        self.bob = User.objects.create_user("bob")
        self.client.force_authenticate(self.coach)
        created = self.client.post("/api/leagues/", {"name": " Tuesday class "}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.league = created.data
        self.code = created.data["invite_code"]

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def join(self, user, code=None):
        response = self.as_user(user).post("/api/leagues/join/", {"code": code or self.code}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def url(self, rest=""):
        return f"/api/leagues/{self.league['id']}/{rest}"

    def own_playbook(self, name="Coach's book"):
        house = next(book for book in self.client.get("/api/practice/playbooks/").data if book["house"])
        response = self.client.post("/api/practice/playbooks/", {"copy_of": house["id"], "name": name}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data


class MembershipTests(ClassTestCase):
    def test_the_maker_owns_and_coaches_a_new_class_with_an_invite_code(self):
        self.assertEqual(self.league["name"], "Tuesday class")
        self.assertEqual(self.league["role"], "coach")
        self.assertEqual(len(self.code), 8)
        listed = self.client.get("/api/leagues/").data
        self.assertEqual(
            [(row["name"], row["role"], row["member_count"]) for row in listed], [("Tuesday class", "coach", 1)]
        )

    def test_joining_by_code_ignores_case_spaces_and_dashes_and_twice_changes_nothing(self):
        typed = f"{self.code[:4].lower()}-{self.code[4:]} "
        data = self.join(self.alice, typed)
        self.join(self.alice)

        self.assertEqual(data["role"], "member")
        self.assertEqual(Membership.objects.filter(user=self.alice).count(), 1)

    def test_a_wrong_code_is_refused(self):
        response = self.as_user(self.alice).post("/api/leagues/join/", {"code": "NOPE2345"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.data)

    def test_a_member_sees_the_coaches_and_themselves_but_not_the_code_or_other_members(self):
        self.join(self.alice)
        data = self.join(self.bob)

        self.assertIsNone(data["invite_code"])
        self.assertEqual(data["member_count"], 3)
        self.assertEqual(sorted(member["name"] for member in data["members"]), ["bob", "coach"])
        coach_view = self.client.get(self.url()).data
        self.assertEqual(sorted(member["name"] for member in coach_view["members"]), ["alice", "bob", "coach"])

    def test_someone_not_in_the_class_cant_see_it(self):
        self.assertEqual(self.as_user(self.alice).get(self.url()).status_code, 404)

    def test_a_new_invite_code_stops_the_old_one(self):
        renewed = self.client.patch(self.url(), {"new_invite": True}, format="json").data
        self.assertNotEqual(renewed["invite_code"], self.code)

        response = self.as_user(self.alice).post("/api/leagues/join/", {"code": self.code}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_only_a_coach_renames_the_class(self):
        self.join(self.alice)
        response = self.as_user(self.alice).patch(self.url(), {"name": "Mine now"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_the_owner_cant_leave_and_stays_a_coach(self):
        self.assertEqual(self.client.delete(self.url("me/")).status_code, 400)
        own = Membership.objects.get(user=self.coach)
        response = self.client.patch(self.url(f"members/{own.pk}/"), {"role": "member"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_a_coach_can_make_a_member_a_coach(self):
        self.join(self.alice)
        member = Membership.objects.get(user=self.alice)
        response = self.client.patch(self.url(f"members/{member.pk}/"), {"role": "coach"}, format="json")
        self.assertEqual(response.data["role"], "coach")
        self.assertIsNotNone(self.as_user(self.alice).get(self.url()).data["invite_code"])


class PlaybookAssignmentTests(ClassTestCase):
    def test_a_coach_assigns_their_playbook_and_members_can_read_and_play_by_it(self):
        self.join(self.alice)
        playbook = self.own_playbook()
        response = self.client.post(
            self.url("assignments/"), {"kind": "playbook", "playbook": playbook["id"], "note": "Week 1"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

        alice = self.as_user(self.alice)
        visible = {book["id"]: book for book in alice.get("/api/practice/playbooks/").data}
        self.assertIn(playbook["id"], visible)
        self.assertFalse(visible[playbook["id"]]["mine"])
        self.assertEqual(alice.get(f"/api/practice/playbooks/{playbook['id']}/").status_code, 200)
        self.assertEqual(self.client.get("/api/practice/playbooks/").data[-1]["classes"], ["Tuesday class"])

    def test_a_new_version_moves_the_assignment_and_putting_it_away_withdraws_it(self):
        self.join(self.alice)
        playbook = self.own_playbook()
        self.client.post(self.url("assignments/"), {"kind": "playbook", "playbook": playbook["id"]}, format="json")
        detail = self.client.get(f"/api/practice/playbooks/{playbook['id']}/").data
        body = {"name": "Coach's book, v2", "description": detail["description"], "rules": detail["rules"]}
        version = self.client.put(f"/api/practice/playbooks/{playbook['id']}/", body, format="json")
        self.assertEqual(version.status_code, 200, version.data)

        assigned = self.as_user(self.alice).get(self.url()).data["assignments"]
        self.assertEqual([row["playbook"]["version"] for row in assigned], [2])

        self.client.delete(f"/api/practice/playbooks/{version.data['id']}/")
        self.assertEqual(self.as_user(self.alice).get(self.url()).data["assignments"], [])

    def test_only_a_coach_assigns_and_only_their_own_playbooks(self):
        self.join(self.alice)
        house = next(book for book in self.client.get("/api/practice/playbooks/").data if book["house"])
        response = self.client.post(
            self.url("assignments/"), {"kind": "playbook", "playbook": house["id"]}, format="json"
        )
        self.assertEqual(response.status_code, 400)

        alices = self.as_user(self.alice)
        own = alices.post("/api/practice/playbooks/", {"copy_of": house["id"], "name": "Alice's"}, format="json").data
        response = alices.post(self.url("assignments/"), {"kind": "playbook", "playbook": own["id"]}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_someone_outside_the_class_cant_read_its_playbook(self):
        playbook = self.own_playbook()
        self.client.post(self.url("assignments/"), {"kind": "playbook", "playbook": playbook["id"]}, format="json")
        self.assertEqual(self.as_user(self.bob).get(f"/api/practice/playbooks/{playbook['id']}/").status_code, 404)


class SharedHandTests(ClassTestCase):
    def setUp(self):
        super().setUp()
        self.join(self.alice)
        self.join(self.bob)
        add_stream(self.alice, "postflop_leaks.txt")
        self.hand = Hand.objects.filter(user=self.alice).order_by("pk").first()
        self.alices = self.as_user(self.alice)
        self.bobs = self.as_user(self.bob)

    def share(self, hand=None):
        hand = hand or self.hand
        body = {"kind": "hand", "hand": hand.pk, "note": "What about the river?"}
        response = self.alices.post(self.url("assignments/"), body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def shared_set(self, client):
        response = client.post("/api/practice/sets/", {"kind": "shared", "tz": "UTC"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def share_all(self):
        for hand in Hand.objects.filter(user=self.alice):
            self.alices.post(self.url("assignments/"), {"kind": "hand", "hand": hand.pk}, format="json")

    def test_sharing_a_hand_makes_an_anonymized_share_and_the_class_sees_no_names(self):
        assigned = self.share()

        share = HandShare.objects.get(user=self.alice, hand=self.hand)
        self.assertTrue(share.anonymize)
        self.assertEqual(assigned["hand"]["own_hand"], self.hand.pk)
        seen = self.bobs.get(self.url()).data["assignments"][0]
        self.assertEqual((seen["by_name"], seen["note"]), ("alice", "What about the river?"))
        self.assertIsNone(seen["hand"]["own_hand"])
        self.assertFalse(seen["can_withdraw"])

    def test_only_your_own_hands_can_be_shared(self):
        response = self.bobs.post(self.url("assignments/"), {"kind": "hand", "hand": self.hand.pk}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_class_members_practise_shared_hands_from_the_sharers_seat_without_names(self):
        self.share_all()
        data = self.shared_set(self.bobs)

        self.assertTrue(data["spots"])
        names = {player["name"] for player in self.hand.replay["players"]}
        for spot in data["spots"]:
            scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
            hand = spot["scenario"]["spec"]["hand"]
            with self.subTest(scenario=scenario.pk):
                self.assertEqual((scenario.source, scenario.owner), ("shared", None))
                self.assertEqual(hand["hero"], "Hero")
                self.assertFalse(names & {player["name"] for player in hand["players"]} - {"Hero"})
        attempt = self.client_answer(self.bobs, data["spots"][0], data["id"])
        self.assertIsNone(attempt["answer"]["result"]["hand"])
        self.assertEqual(attempt["answer"]["player"], "alice")

    def test_the_sharer_doesnt_get_their_own_hands_back(self):
        self.share_all()
        self.assertEqual(self.shared_set(self.alices)["spots"], [])

    def test_a_withdrawn_or_revoked_hand_leaves_future_sets_and_strangers_cant_answer(self):
        self.share_all()
        spot = self.shared_set(self.bobs)["spots"][0]
        stranger = self.as_user(User.objects.create_user("eve"))
        body = {"scenario": spot["scenario"]["id"], "action": "fold", "tz": "UTC"}
        self.assertEqual(stranger.post("/api/practice/attempts/", body, format="json").status_code, 400)

        for assignment in Assignment.objects.filter(kind="hand")[:3]:
            self.assertEqual(self.alices.delete(self.url(f"assignments/{assignment.pk}/")).status_code, 204)
        HandShare.objects.filter(user=self.alice).update(revoked=True)
        self.assertEqual(self.shared_set(self.bobs)["spots"], [])
        self.assertEqual(self.bobs.get(self.url()).data["assignments"], [])

    def test_a_member_cant_withdraw_someone_elses_hand_but_a_coach_can(self):
        assigned = self.share()
        self.assertEqual(self.bobs.delete(self.url(f"assignments/{assigned['id']}/")).status_code, 403)
        self.assertEqual(self.client.delete(self.url(f"assignments/{assigned['id']}/")).status_code, 204)

    def test_leaving_withdraws_what_you_shared(self):
        self.share()
        self.assertEqual(self.alices.delete(self.url("me/")).status_code, 204)
        self.assertEqual(self.bobs.get(self.url()).data["assignments"], [])

    @staticmethod
    def client_answer(client, spot, set_id):
        scenario = Scenario.objects.get(pk=spot["scenario"]["id"])
        advice = scenario.answer.get("advice")
        move = {"action": advice["action"] if advice else "fold"}
        if move["action"] in ("bet", "raise"):
            move["amount"] = scenario.spec["legal"]["min_to"]
        if move["action"] == "fold" and scenario.spec["legal"]["can_check"]:
            move["action"] = "check"
        body = {"scenario": scenario.pk, "set": set_id, "tz": "UTC", **move}
        response = client.post("/api/practice/attempts/", body, format="json")
        assert response.status_code == 201, response.data
        return response.data


class ProgressTests(ClassTestCase):
    def setUp(self):
        super().setUp()
        self.join(self.alice)
        self.join(self.bob)
        playbook = self.own_playbook()
        self.client.post(self.url("assignments/"), {"kind": "playbook", "playbook": playbook["id"]}, format="json")
        add_stream(self.alice, "postflop_leaks.txt")

    def test_coaches_see_only_members_who_share_and_only_totals(self):
        self.assertEqual(self.client.get(self.url("progress/")).data, [])
        shared = self.as_user(self.alice).patch(self.url("me/"), {"shares_progress": True}, format="json")
        self.assertTrue(shared.data["shares_progress"])

        rows = self.client.get(self.url("progress/")).data
        self.assertEqual([row["name"] for row in rows], ["alice"])
        self.assertEqual(set(rows[0]), {"member", "name", "skills", "playbooks"})
        self.assertEqual(rows[0]["playbooks"][0]["name"], "Coach's book")
        self.assertNotIn("book", rows[0]["playbooks"][0])

    def test_one_members_progress_adds_by_the_book(self):
        self.as_user(self.alice).patch(self.url("me/"), {"shares_progress": True}, format="json")
        member = Membership.objects.get(user=self.alice)

        found = self.client.get(self.url(f"progress/{member.pk}/")).data
        self.assertIn("book", found["playbooks"][0])
        self.assertTrue(any(rule["could"] for rule in found["playbooks"][0]["book"]))
        bob = Membership.objects.get(user=self.bob)
        self.assertEqual(self.client.get(self.url(f"progress/{bob.pk}/")).status_code, 404)

    def test_members_cant_see_progress(self):
        self.assertEqual(self.as_user(self.alice).get(self.url("progress/")).status_code, 403)


class ClosedTests(APITestCase):
    """Classes aren't open yet (settings.CLASSES_ENABLED off, the default): their API answers nothing."""

    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.client.force_authenticate(self.user)

    def test_every_classes_endpoint_is_not_found(self):
        for method, url in (
            ("get", "/api/leagues/"),
            ("post", "/api/leagues/"),
            ("post", "/api/leagues/join/"),
            ("get", "/api/leagues/1/"),
            ("post", "/api/leagues/1/assignments/"),
            ("get", "/api/leagues/1/progress/"),
        ):
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {"name": "Tuesday", "code": "ABCD2345"}, format="json")
                self.assertEqual(response.status_code, 404)
        self.assertFalse(League.objects.exists())

    def test_a_shared_practice_set_is_refused(self):
        response = self.client.post("/api/practice/sets/", {"kind": "shared", "tz": "UTC"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("kind", response.data)
