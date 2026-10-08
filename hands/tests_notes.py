from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIClient, APITestCase

from hands.models import Hand, HandNote
from hands.notes import bets
from hands.stats import proportion
from hands.store import store_hands
from hands.tests import add_stream, schema_properties
from tracker import parsing
from tracker.tests_parsing import fixture

User = get_user_model()


def street(name):
    return {"type": "street", "street": name}


def move(street_, player, kind, amount=None):
    event = {"type": kind, "street": street_, "player": player}
    if amount is not None:
        event["amount"] = amount
    return event


class BetsTests(SimpleTestCase):
    def test_each_bet_has_its_street_size_pot_and_what_came_of_it(self):
        events = [
            move("preflop", "Bob", "post", 1),
            move("preflop", "Alice", "post", 2),
            move("preflop", "Bob", "raise", 5),
            move("preflop", "Alice", "raise", 16),  # a 3-bet into 8
            move("preflop", "Bob", "call", 12),
            street("flop"),
            move("flop", "Alice", "bet", 18),  # into 36
            move("flop", "Bob", "raise", 54),
            move("flop", "Alice", "call", 36),
            street("turn"),
            move("turn", "Alice", "check"),
            move("turn", "Bob", "check"),
            street("river"),
            move("river", "Alice", "bet", 100),  # into 144
            move("river", "Bob", "fold"),
            {"type": "return", "street": "river", "player": "Alice", "amount": 100},
        ]

        self.assertEqual(
            [(bet["street"], bet["amount"], bet["pot_before"], bet["outcome"]) for bet in bets(events, "Alice")],
            [("preflop", 16, 8, "called"), ("flop", 18, 36, "raised"), ("river", 100, 144, "folded")],
        )

    def test_a_call_after_a_raise_leaves_it_raised(self):
        events = [
            move("flop", "Alice", "bet", 10),
            move("flop", "Bob", "raise", 30),
            move("flop", "Carol", "call", 30),
        ]

        self.assertEqual(bets(events, "Alice")[0]["outcome"], "raised")

    def test_no_bets_no_purposes(self):
        self.assertEqual(bets([move("preflop", "Alice", "fold")], "Alice"), [])


class HandNotesTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.stream = add_stream(self.user, "play_money.txt")
        self.client.force_authenticate(self.user)
        # Alice raised before the flop, bet the flop and bet the turn.
        self.hand = Hand.objects.get(hand_id="262289822697")
        self.url = f"/api/hands/{self.hand.pk}/notes/"

    def post(self, status=201, **data):
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def test_a_note_on_a_street_is_saved_and_changed_in_place(self):
        first = self.post(kind="note", street="flop", text="Too thin?")
        second = self.post(200, kind="note", street="flop", text="  Fine: they had a draw.  ")
        self.post(kind="note", text="Played it fast.")

        notes = self.client.get(self.url).data

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(
            [(note["kind"], note["street"], note["text"]) for note in notes],
            [("note", "", "Played it fast."), ("note", "flop", "Fine: they had a draw.")],
        )

    def test_a_tag_is_saved_once_in_lower_case(self):
        self.post(kind="tag", tag="  Ask   a Coach ")
        self.post(200, kind="tag", tag="ask a coach")

        self.assertEqual(list(HandNote.objects.values_list("kind", "value")), [("tag", "ask a coach")])

    def test_a_hand_has_one_review_state(self):
        flagged = self.post(kind="review", review="to_review")
        reviewed = self.post(200, kind="review", review="reviewed")

        self.assertEqual((flagged["id"], reviewed["value"]), (reviewed["id"], "reviewed"))

    def test_a_purpose_is_kept_with_its_bets_street(self):
        note = self.post(kind="purpose", bet=2, purpose="value")

        self.assertEqual((note["bet"], note["street"], note["value"]), (2, "turn", "value"))

    def test_bad_notes_are_rejected(self):
        for data in (
            {"kind": "note", "text": "   "},
            {"kind": "note", "street": "showdown", "text": "Hm"},
            {"kind": "tag", "tag": " "},
            {"kind": "review", "review": "later"},
            {"kind": "purpose", "bet": 3, "purpose": "value"},  # she made three
            {"kind": "purpose", "bet": 0},
            {"kind": "comment", "text": "Hm"},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.url, data, format="json").status_code, 400)

    def test_a_note_is_removed(self):
        note = self.post(kind="tag", tag="cooler")

        response = self.client.delete(f"{self.url}{note['id']}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(HandNote.objects.exists())

    def test_notes_outlast_a_reparse(self):
        self.post(kind="tag", tag="cooler")

        _, hands = parsing.parse(fixture("play_money.txt"), {})
        store_hands(self.stream, hands)

        self.assertEqual(Hand.objects.get(pk=self.hand.pk).notes.count(), 1)

    def test_other_users_hands_and_notes_are_out_of_reach(self):
        note = self.post(kind="tag", tag="cooler")
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        self.assertEqual(client.get(self.url).status_code, 404)
        self.assertEqual(client.post(self.url, {"kind": "tag", "tag": "x"}, format="json").status_code, 404)
        self.assertEqual(client.delete(f"{self.url}{note['id']}/").status_code, 404)

    def test_notes_need_a_signed_in_user(self):
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(APIClient().get("/api/review/").status_code, 401)

    def test_responses_match_the_schema(self):
        note = self.post(kind="tag", tag="cooler")
        self.post(kind="review", review="to_review")
        review = self.client.get("/api/review/").data

        self.assertEqual(set(note), schema_properties("HandNote"))
        self.assertEqual(set(review), schema_properties("ReviewQueue"))
        self.assertEqual(set(review["queue"][0]), schema_properties("ReviewHand"))


class ReviewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "play_money.txt")
        self.client.force_authenticate(self.user)
        self.hands = list(Hand.objects.order_by("played_at"))

    def note(self, hand, kind, value):
        return HandNote.objects.create(user=self.user, hand=hand, kind=kind, value=value)

    def hand_ids(self, **params):
        response = self.client.get("/api/hands/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return [hand["hand_id"] for hand in response.data["results"]]

    def test_the_queue_counts_and_lists_the_latest_flagged_first(self):
        first, second, done = self.hands[:3]
        self.note(first, "review", "to_review")
        self.note(second, "review", "to_review")
        self.note(done, "review", "reviewed")

        review = self.client.get("/api/review/").data

        self.assertEqual((review["to_review"], review["reviewed"]), (2, 1))
        self.assertEqual([hand["hand_id"] for hand in review["queue"]], [second.hand_id, first.hand_id])

    def test_the_users_tags_the_most_used_first(self):
        self.note(self.hands[0], "tag", "tilt")
        self.note(self.hands[1], "tag", "tilt")
        self.note(self.hands[1], "tag", "cooler")

        review = self.client.get("/api/review/").data

        self.assertEqual(review["tags"], [{"tag": "tilt", "hands": 2}, {"tag": "cooler", "hands": 1}])
        self.assertEqual(review["suggested_tags"], ["cooler", "misclick", "tilt", "ask a coach"])

    def test_the_history_narrows_to_flagged_or_tagged_hands(self):
        self.note(self.hands[0], "review", "to_review")
        self.note(self.hands[1], "review", "reviewed")
        self.note(self.hands[1], "tag", "tilt")
        self.note(self.hands[2], "tag", "tilt")

        self.assertEqual(self.hand_ids(review="to_review"), [self.hands[0].hand_id])
        self.assertEqual(self.hand_ids(note_tag="tilt"), [self.hands[2].hand_id, self.hands[1].hand_id])
        self.assertEqual(self.hand_ids(note_tag="tilt", review="reviewed"), [self.hands[1].hand_id])
        self.assertEqual(self.client.get("/api/hands/", {"review": "later"}).status_code, 400)

    def test_another_users_queue_is_their_own(self):
        self.note(self.hands[0], "review", "to_review")
        client = APIClient()
        client.force_authenticate(User.objects.create_user("bob"))

        review = client.get("/api/review/").data

        self.assertEqual((review["to_review"], review["queue"], review["tags"]), (0, [], []))


class PurposeStatsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "steals_and_squeezes.txt")
        self.client.force_authenticate(self.user)
        steal = Hand.objects.get(hand_id="262300000001")  # a raise of 1,800 into 900, which took the pot
        squeeze = Hand.objects.get(hand_id="262300000002")  # 2,800 into 1,500, called; 3,000 into 6,500, raised
        for hand, bet, purpose in ((steal, 0, "bluff"), (squeeze, 0, "bluff"), (squeeze, 1, "value")):
            HandNote.objects.create(user=self.user, hand=hand, kind="purpose", bet=bet, value=purpose)

    def stats(self, **params):
        response = self.client.get("/api/stats/purposes/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_bets_by_purpose_and_street(self):
        value, bluffs = self.stats()

        size = (1800 / 900 + 2800 / 1500) / 2
        self.assertEqual(
            {key: bluffs[key] for key in ("purpose", "street", "bets", "called", "raised", "size", "needed")},
            {
                "purpose": "bluff",
                "street": "preflop",
                "bets": 2,
                "called": 1,
                "raised": 0,
                "size": round(size, 3),
                "needed": round(size / (1 + size), 3),
            },
        )
        self.assertEqual(bluffs["took_pot"], proportion(1, 2))
        self.assertEqual((value["purpose"], value["street"], value["raised"], value["size"]), ("value", "flop", 1, 0.462))

    def test_the_page_filters_apply(self):
        self.assertEqual(self.stats(since="2030-01-01"), [])

    def test_the_rows_match_the_schema(self):
        self.assertEqual(set(self.stats()[0]), schema_properties("PurposeStat"))
