"""tracker.parsing on hand-history fixtures: no database, no uploads."""

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from django.test import SimpleTestCase
from pokerkit import HandHistory

from tracker import parsing
from tracker.parsing import pokerstars

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
