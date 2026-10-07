"""tracker.parsing on hand-history fixtures: no database, no uploads."""

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from django.test import SimpleTestCase
from pokerkit import HandHistory

from tracker import parsing
from tracker.parsing import facts, pokerstars

FIXTURES = Path(__file__).parent / "parsing" / "fixtures"
UNREADABLE = {"run_twice.txt"}  # PokerKit's PHH cannot hold a board run twice


def fixture(name):
    return (FIXTURES / name).read_bytes()


def parse_in_chunks(data, size):
    """Parses `data` the way a tracker uploads it: in chunks of about `size` bytes, each ending at a newline."""
    state, hands, start = {}, [], 0
    while start < len(data):
        end = data.rfind(b"\n", start, start + size) + 1 or data.index(b"\n", start) + 1
        state, new = parsing.parse(data[start:end], state)
        hands += new
        start = end
    return state, hands


def hands_in(name):
    state, hands = parsing.parse(fixture(name), {})
    assert state["hands_failed"] == 0, state
    return hands


def hand_in(name, hand_id=None):
    return next(hand for hand in hands_in(name) if hand_id in (None, hand["hand_id"]))


def player(hand, name):
    return next(player for player in hand["players"] if player["name"] == name)


def events(hand, type_):
    return [event for event in hand["events"] if event["type"] == type_]


READABLE_FIXTURES = sorted(path.name for path in FIXTURES.glob("*.txt") if path.name not in UNREADABLE)


class FramingTests(SimpleTestCase):
    def test_a_file_parses_into_its_hands(self):
        state, hands = parsing.parse(fixture("play_money.txt"), {})

        self.assertEqual(
            [hand["hand_id"] for hand in hands],
            ["262289806991", "262289811345", "262289818894", "262289822697", "262289826745"],
        )
        self.assertEqual(
            state,
            {"hands_seen": 5, "hands_failed": 0, "bytes_seen": len(fixture("play_money.txt")), "partial": ""},
        )

    def test_a_hand_split_across_chunks_waits_for_the_rest(self):
        data = fixture("play_money.txt")
        cut = data.index(b"*** FLOP *** [Ad 2h 3h]")  # in the middle of the second hand

        state, first = parsing.parse(data[:cut], {})
        state, rest = parsing.parse(data[cut:], state)

        self.assertEqual(len(first), 1)
        self.assertTrue(state["partial"] == "" and len(rest) == 4)
        self.assertEqual(rest[0]["hand_id"], "262289811345")

    def test_chunk_boundaries_do_not_change_the_hands(self):
        data = fixture("play_money.txt") + fixture("side_pots.txt")
        _, whole = parsing.parse(data, {})

        for size in (40, 333, 1500):
            with self.subTest(size=size):
                state, hands = parse_in_chunks(data, size)
                self.assertEqual(hands, whole)
                self.assertEqual(state["hands_seen"], 9)

    def test_windows_line_endings_are_read_like_unix_ones(self):
        data = fixture("play_money.txt")

        _, hands = parsing.parse(data.replace(b"\n", b"\r\n"), {})

        self.assertEqual(hands, parsing.parse(data, {})[1])

    def test_a_hand_that_cannot_be_read_is_counted_and_the_rest_still_parse(self):
        broken = b"PokerStars Hand #1:  Hold'em No Limit - 2026/10/04 1:53:44 UTC\n*** SUMMARY ***\n\n\n"

        with self.assertLogs("tracker.parsing", "WARNING"):
            state, hands = parsing.parse(broken + fixture("heads_up.txt"), {})

        self.assertEqual([hand["hand_id"] for hand in hands], ["219700000004"])
        self.assertEqual((state["hands_seen"], state["hands_failed"]), (2, 1))

    def test_a_hand_pokerkit_cannot_read_is_skipped(self):
        with self.assertLogs("tracker.parsing", "WARNING") as logs:
            state, hands = parsing.parse(fixture("run_twice.txt"), {})

        self.assertEqual((hands, state["hands_failed"]), ([], 1))
        self.assertIn("219600000003", logs.output[0])

    def test_text_outside_hands_is_ignored(self):
        _, hands = parsing.parse(b"\xef\xbb\xbf\n\nnot a hand\n" + fixture("heads_up.txt"), {})

        self.assertEqual(len(hands), 1)


class ExtractTests(SimpleTestCase):
    def test_the_table_and_the_heros_result(self):
        hand = hand_in("play_money.txt", "262289806991")

        self.assertEqual(
            {key: hand[key] for key in ("site", "hand_id", "played_at", "game", "currency", "play_money")},
            {
                "site": "pokerstars",
                "hand_id": "262289806991",
                "played_at": datetime(2026, 10, 4, 1, 53, 44, tzinfo=UTC),
                "game": "Hold'em No Limit",
                "currency": "",
                "play_money": True,
            },
        )
        self.assertEqual(
            (hand["small_blind"], hand["big_blind"], hand["table"], hand["max_seats"], hand["button_seat"]),
            (100, 200, "Naef V", 6, 5),
        )
        self.assertEqual(
            (hand["hero"], hand["hero_position"], hand["hero_cards"], hand["hero_net"]),
            ("Alice", "UTG", ["Jc", "5c"], -600),
        )
        self.assertEqual((hand["final_street"], hand["total_pot"], hand["rake"]), ("turn", 2800, 154))
        self.assertEqual(hand["board"], ["Kh", "4d", "9h", "As"])

    def test_stacks_carry_over_from_one_hand_to_the_next(self):
        for name in ("play_money.txt", "side_pots.txt"):
            hands = hands_in(name)
            for hand, after in pairwise(hands):
                stacks = {player["name"]: player["stack"] for player in after["players"]}
                for seat in hand["players"]:
                    if seat["name"] in stacks:
                        with self.subTest(hand=hand["hand_id"], player=seat["name"]):
                            self.assertEqual(seat["stack"] + seat["net"], stacks[seat["name"]])

    def test_the_pot_is_what_the_players_put_in(self):
        for name in READABLE_FIXTURES:
            for hand in hands_in(name):
                with self.subTest(hand=hand["hand_id"]):
                    put_in = sum(player["won"] - player["net"] for player in hand["players"])
                    self.assertEqual(put_in, hand["total_pot"])

    def test_pokerkit_pays_out_what_pokerstars_did_after_the_rake(self):
        hand = hand_in("play_money.txt", "262289806991")

        self.assertEqual(
            events(hand, "collect"),
            [{"type": "collect", "street": "turn", "player": "Bob", "amount": 2646, "pot": "pot"}],
        )
        self.assertEqual(player(hand, "Bob")["net"], 1846)

    def test_different_winners_split_the_rake_between_their_pots(self):
        hand = hand_in("split_pots.txt")

        self.assertEqual(
            [(event["player"], event["amount"], event["pot"]) for event in events(hand, "collect")],
            [("Bob", 8505, "main pot"), ("Carol", 13230, "side pot")],
        )
        self.assertEqual([player["net"] for player in hand["players"]], [-10000, 5505, 3230])

    def test_positions_follow_the_button_and_the_blinds(self):
        # Ivan returns and posts both blinds, Erin is new and posts a big blind out of turn.
        hand = hand_in("play_money.txt", "262289811345")

        self.assertEqual(
            {player["name"]: player["position"] for player in hand["players"]},
            {"Ivan": "CO", "Carol": "BTN", "Dave": "SB", "Alice": "BB", "Bob": "UTG", "Erin": "HJ"},
        )

    def test_heads_up_the_button_is_the_small_blind(self):
        hand = hand_in("heads_up.txt")

        self.assertEqual([player["position"] for player in hand["players"]], ["BTN", "BB"])

    def test_players_sitting_out_are_not_in_the_hand(self):
        hand = hand_in("play_money.txt", "262289826745")

        self.assertEqual(
            [(player["seat"], player["name"], player["position"]) for player in hand["players"]],
            [(2, "Carol", "SB"), (3, "Dave", "BB"), (4, "Alice", "UTG"), (5, "Bob", "BTN")],
        )

    def test_middle_positions(self):
        self.assertEqual(pokerstars.middle_positions(1), ["UTG"])
        self.assertEqual(pokerstars.middle_positions(3), ["UTG", "HJ", "CO"])
        self.assertEqual(pokerstars.middle_positions(6), ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"])

    def test_a_returning_players_small_blind_is_dead_money(self):
        hand = hand_in("play_money.txt", "262289811345")

        ivan_posts = [event for event in events(hand, "post") if event["player"] == "Ivan"]

        self.assertEqual(
            ivan_posts,
            [
                {
                    "type": "post",
                    "street": "preflop",
                    "player": "Ivan",
                    "blind": "dead small blind",
                    "amount": 100,
                    "dead": 100,
                },
                {"type": "post", "street": "preflop", "player": "Ivan", "blind": "big blind", "amount": 200},
            ],
        )
        self.assertEqual(player(hand, "Ivan")["net"], 7272)

    def test_a_raise_puts_in_what_brings_the_bet_up_to_its_total(self):
        hand = hand_in("play_money.txt", "262289826745")

        alice_raises = [event for event in events(hand, "raise") if event["player"] == "Alice"]

        self.assertEqual(
            [(event["by"], event["to"], event["amount"]) for event in alice_raises],
            [(800, 1600, 1600), (1200, 4000, 2400)],
        )
        self.assertEqual(hand["hero_net"], -4200)

    def test_shown_hands_are_ranked_by_pokerkit(self):
        hand = hand_in("play_money.txt", "262289811345")

        self.assertEqual(
            [(event["player"], event["cards"], event["description"]) for event in events(hand, "show")],
            [("Ivan", ["3d", "3c"], "Three of a kind")],
        )

    def test_mucked_cards_come_from_the_summary(self):
        hand = hand_in("play_money.txt", "262289811345")

        self.assertEqual(
            [(event["player"], event.get("cards")) for event in events(hand, "muck")],
            [("Carol", ["8h", "Jh"]), ("Dave", ["Ah", "Qh"])],
        )
        self.assertEqual(player(hand, "Carol")["cards"], ["8h", "Jh"])

    def test_an_uncalled_bet_goes_back(self):
        hand = hand_in("side_pots.txt", "262289593035")

        self.assertEqual(
            events(hand, "return"), [{"type": "return", "street": "preflop", "player": "Heidi", "amount": 899}]
        )
        self.assertEqual(player(hand, "Heidi")["net"], -4245)

    def test_money_games_count_in_cents(self):
        hand = hand_in("zoom_usd.txt")

        self.assertEqual(
            (hand["hand_id"], hand["currency"], hand["play_money"], hand["small_blind"], hand["big_blind"]),
            ("219396263497", "USD", False, 5, 10),
        )
        self.assertEqual((hand["hero_net"], hand["total_pot"], hand["rake"]), (383, 809, 24))
        self.assertEqual(player(hand, "Erin")["stack"], 402)

    def test_the_time_is_read_from_eastern_time_when_utc_is_not_given(self):
        self.assertEqual(hand_in("zoom_usd.txt")["played_at"], datetime(2020, 9, 22, 13, 42, 13, tzinfo=UTC))
        self.assertEqual(hand_in("tournament.txt")["played_at"], datetime(2020, 9, 23, 1, 5, tzinfo=UTC))

    def test_a_tournament_hand(self):
        hand = hand_in("tournament.txt")

        self.assertEqual(
            (hand["tournament_id"], hand["game"], hand["small_blind"], hand["big_blind"], hand["ante"]),
            ("2981073415", "Hold'em No Limit", 25, 50, 5),
        )
        self.assertEqual(
            {player["name"]: (player["position"], player["net"]) for player in hand["players"]},
            {"Alice": ("BTN", 2130), "Bob": ("SB", -1490), "Carol": ("BB", -640)},
        )
        self.assertEqual({event["dead"] for event in events(hand, "post") if event["blind"] == "ante"}, {5})

    def test_an_omaha_hand(self):
        hand = hand_in("omaha_eur.txt")

        self.assertEqual(
            (hand["game"], hand["currency"], hand["hero_cards"]), ("Omaha Pot Limit", "EUR", ["Ah", "As", "7d", "6c"])
        )
        self.assertEqual((hand["hero_position"], hand["hero_net"], hand["final_street"]), ("SB", 91, "turn"))

    def test_the_events_of_a_hand(self):
        hand = hand_in("heads_up.txt")

        self.assertEqual(
            hand["events"],
            [
                {"type": "post", "street": "preflop", "player": "Bob", "blind": "big blind", "amount": 20},
                {"type": "post", "street": "preflop", "player": "Alice", "blind": "small blind", "amount": 10},
                {"type": "deal", "street": "preflop", "player": "Alice", "cards": ["7c", "2d"]},
                {"type": "fold", "street": "preflop", "player": "Alice"},
                {"type": "return", "street": "preflop", "player": "Bob", "amount": 10},
                {"type": "collect", "street": "preflop", "player": "Bob", "amount": 20, "pot": "pot"},
            ],
        )

    def test_streets_carry_the_new_cards_and_the_whole_board(self):
        hand = hand_in("play_money.txt", "262289806991")

        self.assertEqual(
            events(hand, "street"),
            [
                {"type": "street", "street": "flop", "cards": ["Kh", "4d", "9h"], "board": ["Kh", "4d", "9h"]},
                {"type": "street", "street": "turn", "cards": ["As"], "board": ["Kh", "4d", "9h", "As"]},
            ],
        )

    def test_an_all_in_board_runs_out_before_the_showdown(self):
        hand = hand_in("side_pots.txt", "262289593035")

        self.assertEqual(
            [event.get("player", event["street"]) for event in hand["events"][-7:]],
            ["flop", "turn", "river", "showdown", "Mallory", "Heidi", "Mallory"],
        )

    def test_the_hand_is_kept_in_pokerkits_phh_notation(self):
        hand = hand_in("play_money.txt", "262289806991")

        hh = HandHistory.loads(hand["phh"])

        self.assertEqual((hh.variant, hh.hand, hh.table, hh.venue), ("NT", 262289806991, "Naef V", "PokerStars"))
        self.assertEqual((hh.players, hh.seats), (["Carol", "Dave", "Alice", "Bob"], [2, 3, 4, 5]))
        self.assertEqual(hh.blinds_or_straddles, [100, 200, -200, 0])  # Alice is new: her big blind is a post bet
        self.assertIn("d dh p3 Jc5c", hh.actions)
        self.assertEqual((hh.time_zone, str(hh.time)), ("UTC", "01:53:44"))
        self.assertEqual(hh.finishing_stacks, [17567, 57071, 19400, 23224])
        self.assertEqual(hh.user_defined_fields["_rake"], 154)
        self.assertTrue(list(hh))  # PokerKit plays it through again

    def test_text_that_is_not_a_hand_is_an_error(self):
        with self.assertRaises(pokerstars.HandError):
            pokerstars.extract("Hello\nworld\n")


def player_facts(hand, name):
    return next(row for row in hand["facts"]["players"] if row["name"] == name)


def chances(row):
    """A player's statistics that had a chance in the hand, as {name: (could, did)}."""
    return {stat: (row[f"{stat}_could"], row[f"{stat}_did"]) for stat in facts.STATS if row[f"{stat}_could"]}


class FactsTests(SimpleTestCase):
    def test_a_steal_and_the_blinds_answers(self):
        hand = hand_in("steals_and_squeezes.txt", "262300000001")

        carol, erin, alice = (player_facts(hand, name) for name in ("Carol", "Erin", "Alice"))

        self.assertEqual((carol["position"], carol["situation"], carol["first_action"]), ("CO", "unopened", "raise"))
        self.assertEqual(
            {stat: chances(carol)[stat] for stat in ("rfi", "steal", "fold_to_three_bet")},
            {"rfi": (1, 1), "steal": (1, 1), "fold_to_three_bet": (1, 1)},
        )
        self.assertEqual(chances(erin)["fold_to_steal"], (1, 1))
        self.assertEqual(
            {stat: chances(alice)[stat] for stat in ("fold_to_steal", "three_bet_vs_steal", "bb_defend", "three_bet")},
            {"fold_to_steal": (1, 0), "three_bet_vs_steal": (1, 1), "bb_defend": (1, 1), "three_bet": (1, 1)},
        )

    def test_an_open_after_a_limp_is_not_a_steal(self):
        hand = hand_in("play_money.txt", "262289822697")

        alice = player_facts(hand, "Alice")

        self.assertEqual(alice["situation"], "limped")
        self.assertNotIn("rfi", chances(alice))
        self.assertNotIn("steal", chances(alice))
        self.assertNotIn("fold_to_steal", chances(player_facts(hand, "Bob")))

    def test_a_squeeze_and_a_check_raise(self):
        hand = hand_in("steals_and_squeezes.txt", "262300000002")

        alice, bob, dave = (player_facts(hand, name) for name in ("Alice", "Bob", "Dave"))

        self.assertEqual(chances(alice)["squeeze"], (1, 1))
        self.assertEqual(chances(dave)["squeeze"], (1, 0))  # he folded to the raise and the call
        self.assertEqual(
            {stat: chances(bob)[stat] for stat in ("donk_flop", "fold_to_cbet_flop", "check_raise")},
            {"donk_flop": (1, 0), "fold_to_cbet_flop": (1, 0), "check_raise": (1, 1)},
        )
        self.assertEqual(chances(alice)["cbet_flop"], (1, 1))

    def test_continuation_bets_and_the_answers_to_them(self):
        hand = hand_in("play_money.txt", "262289806991")

        bob, carol, dave = (player_facts(hand, name) for name in ("Bob", "Carol", "Dave"))

        self.assertEqual((chances(bob)["cbet_flop"], chances(bob)["cbet_turn"]), ((1, 1), (1, 1)))
        self.assertEqual(chances(carol)["fold_to_cbet_flop"], (1, 1))
        self.assertEqual(
            {stat: chances(dave)[stat] for stat in ("fold_to_cbet_flop", "fold_to_cbet_turn", "check_raise")},
            {"fold_to_cbet_flop": (1, 0), "fold_to_cbet_turn": (1, 1), "check_raise": (2, 0)},  # a chance a street
        )
        self.assertEqual((dave["postflop_calls"], dave["postflop_checks"], dave["postflop_folds"]), (1, 2, 1))

    def test_no_turn_cbet_once_the_flop_cbet_is_raised(self):
        hand = hand_in("omaha_eur.txt")

        dave = player_facts(hand, "Dave")

        self.assertEqual(chances(dave)["cbet_flop"], (1, 1))
        self.assertNotIn("cbet_turn", chances(dave))
        self.assertEqual(chances(player_facts(hand, "Alice"))["check_raise"], (1, 1))

    def test_blinds_and_checks_are_not_voluntary(self):
        # Ivan and Erin post a big blind as they join, then check; Alice checks her option.
        hand = hand_in("play_money.txt", "262289811345")

        for name in ("Ivan", "Erin", "Alice"):
            with self.subTest(player=name):
                self.assertEqual(chances(player_facts(hand, name))["vpip"], (1, 0))
        self.assertEqual(
            {name: chances(player_facts(hand, name))["limp"] for name in ("Bob", "Carol", "Dave")},
            {"Bob": (1, 1), "Carol": (1, 1), "Dave": (1, 1)},
        )
        self.assertEqual(hand["facts"]["hand"]["pot_type"], "limped")

    def test_a_walk_gives_the_big_blind_no_decision(self):
        hand = hand_in("heads_up.txt")

        self.assertNotIn("vpip", chances(player_facts(hand, "Bob")))
        self.assertEqual(chances(player_facts(hand, "Alice"))["steal"], (1, 0))  # heads-up, the button is the SB
        self.assertEqual(hand["facts"]["hand"]["pot_type"], "walk")

    def test_a_raise_a_short_stack_cannot_make_is_no_chance_to_make_it(self):
        hand = hand_in("tournament.txt")

        # Bob's all-in is more than Alice and Carol have left: they can only call or fold.
        self.assertNotIn("four_bet", chances(player_facts(hand, "Alice")))
        self.assertNotIn("four_bet", chances(player_facts(hand, "Carol")))
        self.assertEqual(chances(player_facts(hand, "Alice"))["fold_to_three_bet"], (1, 0))

    def test_no_donk_bet_into_a_player_who_is_all_in(self):
        hand = hand_in("side_pots.txt", "262289596277")

        self.assertNotIn("donk_flop", chances(player_facts(hand, "Mallory")))

    def test_showdowns(self):
        hand = hand_in("play_money.txt", "262289811345")

        self.assertEqual(
            {
                row["name"]: (row["went_to_showdown_did"], row["won_at_showdown_did"])
                for row in hand["facts"]["players"]
            },
            {"Ivan": (1, 1), "Carol": (1, 0), "Dave": (1, 0), "Alice": (0, 0), "Bob": (0, 0), "Erin": (0, 0)},
        )

    def test_results_in_big_blinds(self):
        hand = hand_in("tournament.txt")

        alice = player_facts(hand, "Alice")

        self.assertEqual((alice["stack_bb"], alice["invested_bb"], alice["net_bb"]), (29.8, 29.8, 42.6))
        self.assertEqual(alice["allin_street"], "preflop")
        self.assertEqual(alice["extra"]["m"], 16.56)

    def test_the_hand(self):
        hand = hand_in("tournament.txt")

        columns = hand["facts"]["hand"]

        self.assertEqual(
            {key: columns[key] for key in ("players_dealt", "pot_type", "hero_combo", "hero_situation")},
            {"players_dealt": 3, "pot_type": "3bet", "hero_combo": "88", "hero_situation": "unopened"},
        )
        self.assertEqual(
            (columns["hero_first_action"], columns["effective_bb"], columns["hero_m"]), ("raise", 29.8, 16.56)
        )
        self.assertEqual(columns["facts"]["preflop_aggressor"], "Bob")
        self.assertEqual(columns["facts"]["hero"]["group"], "medium_pair")
        self.assertEqual(columns["facts"]["hero"]["made"], {"flop": "set", "turn": "full_house", "river": "full_house"})

    def test_each_street_has_its_pot_and_stacks(self):
        hand = hand_in("side_pots.txt", "262289601365")

        streets = hand["facts"]["hand"]["facts"]["streets"]

        self.assertEqual(
            {street: row["pot_bb"] for street, row in streets.items()}, {"flop": 5.5, "turn": 9.5, "river": 22.95}
        )
        self.assertEqual((streets["flop"]["players"], streets["turn"]["players"]), (5, 4))
        self.assertEqual(hand["facts"]["hand"]["facts"]["hero"]["spr"], 17.0)  # Alice's 18,701 against a 1,100 pot

    def test_an_omaha_hero_gets_pokerkits_categories(self):
        hand = hand_in("omaha_eur.txt")

        columns = hand["facts"]["hand"]

        self.assertEqual((columns["hero_combo"], columns["facts"]["hero"]["group"]), ("", ""))
        self.assertEqual(columns["facts"]["hero"]["made"], {"flop": "three_of_a_kind", "turn": "three_of_a_kind"})

    def test_did_never_outnumbers_could(self):
        for name in READABLE_FIXTURES:
            for hand in hands_in(name):
                for row in hand["facts"]["players"]:
                    for stat in facts.STATS:
                        with self.subTest(hand=hand["hand_id"], player=row["name"], stat=stat):
                            self.assertLessEqual(row[f"{stat}_did"], row[f"{stat}_could"])
                    self.assertLessEqual(row["pfr_did"], row["vpip_did"])


class HoldingTests(SimpleTestCase):
    def test_combos(self):
        self.assertEqual(
            [facts.combo(cards) for cards in (["Kd", "As"], ["9h", "Th"], ["8s", "8h"], ["2c", "Td"])],
            ["AKo", "T9s", "88", "T2o"],
        )

    def test_hand_groups(self):
        groups = {
            "premium": (["As", "Ad"], ["Ah", "Kd"]),
            "big_pair": (["Js", "Jd"],),
            "medium_pair": (["9s", "9d"], ["7c", "7h"]),
            "small_pair": (["6s", "6d"], ["2c", "2h"]),
            "big_ace": (["Ac", "Qd"],),
            "suited_connector": (["Jh", "Th"], ["5d", "4d"]),
            "trouble": (["Ks", "Qd"], ["Ac", "Jd"], ["Qh", "Jc"]),
            "weak_ace": (["Ad", "9c"], ["As", "2s"]),
            "junk": (["7c", "2d"], ["Kh", "3h"], ["4s", "3s"]),
        }
        for group, hands in groups.items():
            for cards in hands:
                with self.subTest(cards=cards):
                    self.assertEqual(facts.hand_group(cards), group)

    def test_made_hands(self):
        cases = [
            (["8s", "8h"], ["2c", "8d", "Kh"], "set"),
            (["Ks", "7h"], ["Kd", "Kc", "2h"], "trips"),
            (["Ks", "7h"], ["Kd", "7c", "2h"], "two_pair"),
            (["Qs", "Qh"], ["Jc", "7d", "2s"], "overpair"),
            (["9s", "9h"], ["Jc", "7d", "2s"], "pocket_pair"),
            (["5s", "5h"], ["Jc", "7d", "6s"], "underpair"),
            (["Ah", "Kd"], ["Kc", "7d", "2s"], "top_pair_top_kicker"),
            (["Ah", "Kd"], ["Ac", "7d", "2s"], "top_pair_top_kicker"),  # with aces paired the king is the best
            (["Kh", "2d"], ["Qs", "Kd", "Ts"], "top_pair"),
            (["Ah", "7d"], ["Kc", "7c", "2s"], "second_pair"),
            (["Ah", "2d"], ["Kc", "7c", "2s"], "bottom_pair"),
            (["Ah", "Kd"], ["Kc", "7c", "7s"], "top_pair_top_kicker"),  # the board's pair is everyone's
            (["Ah", "Kd"], ["9c", "7c", "2s"], "overcards"),
            (["9h", "8d"], ["Kc", "Kd", "7h", "7s"], "high_card"),  # the board's two pair plays
            (["9h", "8d"], ["Tc", "7c", "2s", "6d"], "straight"),
        ]
        for hole, board, made in cases:
            with self.subTest(hole=hole, board=board):
                self.assertEqual(facts.made_hand(hole, board), made)

    def test_draws(self):
        cases = [
            (["Ah", "5h"], ["Kh", "9h", "2c"], ["nut_flush_draw"]),
            (["Kh", "5h"], ["Ah", "9h", "2c"], ["nut_flush_draw"]),  # with the ace on the board, the king is the best
            (["Kh", "5h"], ["Qh", "9h", "2c"], ["flush_draw"]),  # the ace is still out
            (["Qh", "5h"], ["Kh", "9h", "2c"], ["flush_draw"]),
            (["Qh", "5h"], ["Kh", "9c", "2c"], ["backdoor_flush_draw"]),
            (["9d", "8c"], ["7h", "6s", "Kd"], ["open_ended"]),
            (["8d", "6c"], ["Th", "7s", "4d"], ["double_gutshot"]),  # a five or a nine
            (["Ad", "Kc"], ["Qh", "Js", "4d"], ["gutshot"]),  # only a ten fills it
            (["2d", "3c"], ["4h", "5s", "Kd"], ["open_ended"]),  # an ace or a six
            (["9d", "2c"], ["Th", "Js", "Qd", "4c"], ["open_ended"]),
            (["Kd", "2c"], ["9h", "Ts", "Jd", "Qc"], []),  # a straight already
            (["Ah", "5h"], ["Kh", "9h", "2c", "3s", "7d"], []),  # no draws on the river
        ]
        for hole, board, found in cases:
            with self.subTest(hole=hole, board=board):
                self.assertEqual(facts.draws(hole, board), found)

    def test_board_textures(self):
        self.assertEqual(
            facts.board_texture(["Kh", "7d", "2c"]),
            {"paired": False, "suited": 1, "straight_possible": False, "high_card": "K", "wetness": 0},
        )
        self.assertEqual(
            facts.board_texture(["Jh", "Th", "9h"]),
            {"paired": False, "suited": 3, "straight_possible": True, "high_card": "J", "wetness": 3},
        )
        self.assertTrue(facts.board_texture(["As", "4d", "4c", "3h"])["paired"])
        self.assertTrue(facts.board_texture(["As", "3d", "4c"])["straight_possible"])  # the wheel
