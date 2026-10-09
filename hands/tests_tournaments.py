from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from hands.models import Tournament
from hands.stats import proportion
from hands.tests import add_stream, schema_properties
from hands.tournaments import result

User = get_user_model()


class TournamentTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice")
        add_stream(self.user, "tournament_finishes.txt")
        add_stream(self.user, "tournament.txt")
        add_stream(self.user, "play_money.txt")
        self.client.force_authenticate(self.user)

    def tournament(self, number):
        return Tournament.objects.get(user=self.user, tournament_id=number)

    def test_a_knockout_tournament_the_hero_won(self):
        won = self.tournament("3100000001")

        self.assertEqual(
            (won.buy_in, won.bounty, won.fee, won.currency, won.hands, won.top_level, won.max_seats),
            (100, 100, 20, "USD", 3, 3, 9),
        )
        self.assertEqual((won.finish, won.prize, won.bounties_won, won.knockouts, won.entries), (1, 260, 200, 3, 1))
        # $2.60 and $2 of bounties for $2.20.
        self.assertEqual((result(won)["net"], result(won)["roi"]), (240, 1.0909))

    def test_a_bust_played_on_from_is_a_re_entry(self):
        cashed = self.tournament("3100000002")

        self.assertEqual((cashed.entries, cashed.finish, cashed.prize), (2, 2, 144))
        self.assertEqual(result(cashed)["net"], 144 - 2 * 110)

    def test_a_tournament_without_a_finish(self):
        open_ = self.tournament("2981073415")

        self.assertEqual((open_.finish, open_.prize), (None, None))
        self.assertEqual((result(open_)["net"], result(open_)["in_the_money"]), (-110, False))

    def test_storing_the_hands_again_keeps_the_users_entries(self):
        Tournament.objects.filter(pk=self.tournament("2981073415").pk).update(entered_finish=3, field_size=9)
        add_stream(self.user, "tournament.txt")

        tournament = self.tournament("2981073415")
        self.assertEqual((tournament.entered_finish, tournament.field_size, result(tournament)["percentile"]), (3, 9, 0.25))

    def test_payouts_give_a_prize_to_a_finish(self):
        tournament = self.tournament("2981073415")
        tournament.entered_finish, tournament.payouts = 2, [300, 180, 120]

        self.assertEqual((result(tournament)["prize"], result(tournament)["in_the_money"]), (180, True))

    def test_the_list_the_latest_first(self):
        rows = self.client.get("/api/tournaments/").data["results"]

        self.assertEqual([row["tournament_id"] for row in rows], ["3100000002", "3100000001", "2981073415"])
        self.assertEqual(rows[1]["kind"], "9-max knockout")
        self.assertEqual(rows[1]["result"]["net"], 240)

    def test_the_summary(self):
        rows = self.client.get("/api/tournaments/summary/").data
        everything = next(row for row in rows if row["kind"] == "all")

        self.assertEqual(
            (everything["money"], everything["tournaments"], everything["entries"], everything["cost"]),
            ("USD", 3, 4, 550),
        )
        self.assertEqual((everything["prizes"], everything["bounties"], everything["net"]), (404, 200, 54))
        self.assertEqual(everything["fees"], 20 + 2 * 12 + 12)
        self.assertEqual(everything["in_the_money"], proportion(2, 2))

    def test_a_tournament_with_the_heros_stack(self):
        tournament = self.tournament("3100000001")

        detail = self.client.get(f"/api/tournaments/{tournament.pk}/").data
        points = detail["timeline"]

        self.assertEqual([point["stack"] for point in points], [1500, 1930, 3435])
        self.assertEqual([point["level"] for point in points], [1, 2, 3])
        self.assertEqual([point["zone"] for point in points], ["set_mining", "set_mining", "set_mining"])
        self.assertEqual([point["all_in"] for point in points], [True, False, False])

    def test_entering_what_the_hands_cant_tell(self):
        tournament = self.tournament("2981073415")

        response = self.client.patch(
            f"/api/tournaments/{tournament.pk}/",
            {"field_size": 45, "payouts": [2000, 1200, 800], "entered_finish": 3},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["result"]["prize"], 800)
        self.assertEqual(response.data["result"]["percentile"], round(2 / 44, 3))

    def test_the_history_of_a_tournament(self):
        tournament = self.tournament("3100000002")

        response = self.client.get("/api/hands/", {"tournament": tournament.pk})

        self.assertEqual(len(response.data["results"]), 3)

    def test_a_replay_knows_its_tournament(self):
        tournament = self.tournament("3100000002")
        hand = self.client.get("/api/hands/", {"tournament": tournament.pk}).data["results"][0]

        detail = self.client.get(f"/api/hands/{hand['id']}/").data

        self.assertEqual((detail["tournament"], detail["level"]), (tournament.pk, 4))

    def test_another_users_tournaments_are_hidden(self):
        other = User.objects.create_user("bob")
        self.client.force_authenticate(other)

        self.assertEqual(self.client.get(f"/api/tournaments/{self.tournament('3100000001').pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/tournaments/").data["results"], [])

    def test_responses_match_the_schema(self):
        tournament = self.tournament("3100000001")

        detail = self.client.get(f"/api/tournaments/{tournament.pk}/").data
        summary = self.client.get("/api/tournaments/summary/").data[0]

        self.assertEqual(set(detail), schema_properties("TournamentDetail"))
        self.assertEqual(set(detail["timeline"][0]), schema_properties("TimelinePoint"))
        self.assertEqual(set(summary), schema_properties("TournamentTotals"))
