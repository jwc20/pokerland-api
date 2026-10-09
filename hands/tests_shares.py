from django.contrib.auth import get_user_model
from django.core.cache import cache
from pokerkit import HandHistory
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandNote, HandShare
from hands.tests import add_stream, schema_properties

User = get_user_model()


class WriteUpTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "play_money.txt")
        self.hand = Hand.objects.filter(user=self.user).first()
        self.client.force_authenticate(self.user)

    def test_a_hand_keeps_one_write_up(self):
        url = f"/api/hands/{self.hand.pk}/notes/"

        first = self.client.post(url, {"kind": "writeup", "text": "Stacks: 100 BB."}, format="json")
        second = self.client.post(url, {"kind": "writeup", "text": "Stacks: 100 BB effective." * 200}, format="json")

        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(HandNote.objects.filter(hand=self.hand, kind="writeup").count(), 1)

    def test_a_street_note_stays_short(self):
        response = self.client.post(
            f"/api/hands/{self.hand.pk}/notes/", {"kind": "note", "text": "x" * 2001}, format="json"
        )

        self.assertEqual(response.status_code, 400)


class ShareTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "play_money.txt")
        self.hand = Hand.objects.get(user=self.user, hand_id="262289826745")
        self.client.force_authenticate(self.user)
        cache.clear()  # the throttle counts in the cache

    def share(self, **fields):
        response = self.client.post("/api/shares/", {"hand": self.hand.pk, **fields}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def public(self, slug):
        return APIClient().get(f"/api/public/shares/{slug}/")

    def test_a_share_is_anonymized_by_default(self):
        share = self.share(write_up="Should I have raised the river?")

        page = self.public(share["slug"])

        self.assertEqual(page.status_code, 200)
        hand = page.data["hand"]
        names = {player["name"] for player in hand["players"]}
        self.assertEqual((page.data["write_up"], page.data["anonymized"]), ("Should I have raised the river?", True))
        self.assertEqual(hand["hero"], "Hero")
        self.assertIn("Hero", names)
        self.assertFalse(names & {"Alice", "Bob", "Carol", "Dave", "Erin", "Ivan"})
        self.assertFalse({event.get("player") for event in hand["events"]} & {"Alice", "Bob", "Carol"})
        self.assertEqual((hand["hand_id"], hand["tournament_id"]), ("", ""))
        self.assertNotIn("table", hand)
        self.assertNotIn("opponents", hand)

    def test_the_phh_is_anonymized_too(self):
        share = self.share()

        phh = self.public(share["slug"]).data["hand"]["phh"]
        history = HandHistory.loads(phh)

        self.assertIn("Hero", history.players)
        self.assertNotIn("Alice", phh)
        self.assertIsNone(history.hand)

    def test_a_share_with_names(self):
        share = self.share(anonymize=False)

        hand = self.public(share["slug"]).data["hand"]

        self.assertEqual(hand["hero"], "Alice")
        self.assertEqual(hand["hand_id"], "262289826745")

    def test_a_revoked_share_is_gone(self):
        share = self.share()
        self.client.patch(f"/api/shares/{share['id']}/", {"revoked": True}, format="json")

        self.assertEqual(self.public(share["slug"]).status_code, 404)

    def test_the_owner_lists_and_deletes_shares(self):
        share = self.share()

        listed = self.client.get("/api/shares/").data
        self.assertEqual([row["slug"] for row in listed], [share["slug"]])
        self.assertEqual(self.client.delete(f"/api/shares/{share['id']}/").status_code, 204)
        self.assertEqual(HandShare.objects.count(), 0)

    def test_only_ones_own_hands_are_shared(self):
        other = User.objects.create_user("bob")
        self.client.force_authenticate(other)

        response = self.client.post("/api/shares/", {"hand": self.hand.pk}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_the_public_page_needs_no_sign_in_and_ignores_a_stale_cookie(self):
        share = self.share()
        client = APIClient()
        client.cookies["access-token"] = "stale"

        self.assertEqual(client.get(f"/api/public/shares/{share['slug']}/").status_code, 200)

    def test_responses_match_the_schema(self):
        share = self.share()

        self.assertEqual(set(share), schema_properties("HandShare"))
        self.assertEqual(set(self.public(share["slug"]).data), schema_properties("PublicShare"))
        self.assertEqual(set(self.public(share["slug"]).data["hand"]), schema_properties("PublicHand"))
