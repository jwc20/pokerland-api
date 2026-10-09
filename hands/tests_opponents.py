from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from hands.models import Opponent
from hands.opponents import label
from hands.stats import proportion
from hands.tests import StatsTests, add_stream, schema_properties

User = get_user_model()


def stats(vpip, vpip_could, aggressive, moves, pfr=0):
    return {
        "vpip": proportion(vpip, vpip_could),
        "pfr": proportion(pfr, vpip_could),
        "aggression": proportion(aggressive, moves),
    }


class LabelTests(APITestCase):
    def test_too_few_hands_have_no_label(self):
        self.assertEqual(label(19, stats(10, 19, 5, 10)), ("", ""))

    def test_the_four_types(self):
        self.assertEqual(label(200, stats(80, 200, 60, 100))[0], "lag")
        self.assertEqual(label(200, stats(30, 200, 60, 100))[0], "tag")
        self.assertEqual(label(200, stats(80, 200, 20, 100))[0], "station")
        self.assertEqual(label(200, stats(30, 200, 20, 100))[0], "rock")

    def test_confidence_from_the_ranges(self):
        self.assertEqual(label(400, stats(160, 400, 120, 200)), ("lag", "high"))  # 40% and 60%, both clear
        self.assertEqual(label(40, stats(12, 40, 9, 20)), ("lag", "low"))  # 30% and 45%, neither clear
        self.assertEqual(label(400, stats(160, 400, 9, 20)), ("lag", "medium"))  # VPIP clear, aggression not

    def test_without_moves_after_the_flop_the_raises_before_it_count(self):
        self.assertEqual(label(60, stats(30, 60, 0, 4, pfr=20)), ("lag", "medium"))


class OpponentTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        for name in StatsTests.FIXTURES:
            add_stream(self.user, name)
        self.client.force_authenticate(self.user)

    def opponent(self, name):
        return Opponent.objects.get(user=self.user, name=name)

    def test_storing_hands_counts_their_opponents(self):
        bob = self.opponent("Bob")

        self.assertEqual(bob.hands, 12)
        self.assertEqual(bob.counters["vpip_could"] >= bob.counters["vpip_did"], True)
        self.assertEqual(Opponent.objects.filter(user=self.user, name="Alice").count(), 0)

    def test_storing_the_same_hands_again_counts_them_once(self):
        add_stream(self.user, "play_money.txt")

        self.assertEqual(self.opponent("Bob").hands, 12)

    def test_the_ledger_counts_the_hands_both_played(self):
        heidi = self.opponent("Heidi")

        # Dealt in together twice: the hero called her raise once, and folded to it once.
        self.assertEqual((heidi.hands, heidi.shared_hands), (2, 1))
        ledger = self.client.get(f"/api/opponents/{heidi.pk}/ledger/").data
        self.assertEqual((ledger["hands"], ledger["net_bb"]), (1, heidi.hero_net_bb))

    def test_the_list_sorts_and_searches(self):
        listed = self.client.get("/api/opponents/").data["results"]
        found = self.client.get("/api/opponents/", {"search": "ud"}).data["results"]

        self.assertEqual([row["name"] for row in listed[:3]], ["Bob", "Carol", "Dave"])
        self.assertEqual([row["name"] for row in found], ["Judy"])

    def test_the_list_by_net(self):
        best = self.client.get("/api/opponents/", {"sort": "best"}).data["results"]
        worst = self.client.get("/api/opponents/", {"sort": "worst"}).data["results"]

        self.assertEqual(best[0]["hero_net_bb"], max(row["hero_net_bb"] for row in best))
        self.assertEqual(worst[0]["hero_net_bb"], min(row["hero_net_bb"] for row in worst))

    def test_a_profile(self):
        bob = self.opponent("Bob")

        profile = self.client.get(f"/api/opponents/{bob.pk}/").data

        self.assertEqual((profile["name"], profile["hands"]), ("Bob", 12))
        self.assertEqual(profile["stats"]["vpip"]["could"], bob.counters["vpip_could"])
        self.assertEqual(sum(row["hands"] for row in profile["positions"]), 12)
        self.assertEqual((profile["loose_vpip"], profile["aggressive"]), (25, 40))

    def test_the_users_own_label_and_note(self):
        bob = self.opponent("Bob")

        response = self.client.patch(
            f"/api/opponents/{bob.pk}/", {"manual_label": "station", "note": "Calls everything"}, format="json"
        )
        cleared = self.client.patch(f"/api/opponents/{bob.pk}/", {"manual_label": ""}, format="json")

        self.assertEqual((response.data["shown_label"], response.data["note"]), ("station", "Calls everything"))
        self.assertEqual(cleared.data["shown_label"], bob.label)

    def test_showdowns_the_most_surprising_first(self):
        mallory = self.opponent("Mallory")

        shown = self.client.get(f"/api/opponents/{mallory.pk}/showdowns/").data

        # Called raises with 5-4 offsuit and 5-3 suited, and limped ace-ten.
        self.assertEqual(
            [(row["combo"], row["line"]) for row in shown],
            [("54o", "called a raise"), ("53s", "called a raise"), ("ATo", "limped")],
        )
        self.assertEqual(set(shown[0]), schema_properties("OpponentShowdown"))

    def test_the_history_with_an_opponent(self):
        judy = self.opponent("Judy")

        response = self.client.get("/api/hands/", {"opponent": judy.pk})

        self.assertEqual(len(response.data["results"]), 4)

    def test_a_replay_links_its_opponents(self):
        bob = self.opponent("Bob")
        hand = self.client.get("/api/hands/").data["results"][0]

        detail = self.client.get(f"/api/hands/{hand['id']}/").data

        self.assertIn({"name": "Bob", "id": bob.pk, "label": bob.label}, detail["opponents"])

    def test_another_users_opponents_are_hidden(self):
        other = User.objects.create_user("bob")
        add_stream(other, "heads_up.txt")
        theirs = Opponent.objects.filter(user=other).first()

        self.assertEqual(self.client.get(f"/api/opponents/{theirs.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/hands/", {"opponent": theirs.pk}).status_code, 400)

    def test_responses_match_the_schema(self):
        bob = self.opponent("Bob")

        self.assertEqual(set(self.client.get(f"/api/opponents/{bob.pk}/").data), schema_properties("OpponentDetail"))
        self.assertEqual(set(self.client.get(f"/api/opponents/{bob.pk}/ledger/").data), schema_properties("Ledger"))
