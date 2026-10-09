"""The practice engines on their own: spots, the playbook's rules, questions, the table, the bots, the generators.

No database: like tracker.parsing they run on fixture files and on hands played here.
"""

import random
import warnings
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from hands import ranges
from practice import bots, charts, generators, library, ratings, rules, sets
from practice.playbook import HOUSE, STARTER
from practice.questions import arithmetic, money
from practice.spots import decisions, hand_class, pending
from practice.table import IllegalMove, TableHand, shuffled_deck
from tracker.tests_parsing import hand_in

RULES = STARTER["rules"]
HERO, VILLAIN = generators.HERO, generators.VILLAIN


def heads_up(first=(), hero_on_button=False, stack_bb=100):
    """A heads-up hand dealing `first` first: the big blind's cards, the button's, a burn, the flop, ..."""
    return generators.table(random.Random(1), stack_bb, hero_on_button, first)


def now(table, name=HERO):
    """The context of `name`'s decision at the table."""
    return pending(table.replay(name))


def card(rule_id):
    return next(rule for rule in RULES if rule["id"] == rule_id)


class SpotTests(SimpleTestCase):
    """practice.spots: what each of the hero's decisions faced."""

    def setUp(self):
        # Bob opens, Carol calls, Alice squeezes with kings and is called; she sets the flop, bets, and folds to a
        # check-raise.
        self.hand = hand_in("steals_and_squeezes.txt", "262300000002")
        self.squeeze, self.cbet, self.fold = decisions(self.hand)

    def test_each_decision_and_the_move_made(self):
        self.assertEqual([d["step"] for d in decisions(self.hand)], [6, 13, 15])
        self.assertEqual([d["move"]["action"] for d in decisions(self.hand)], ["raise", "bet", "fold"])

    def test_the_price_of_a_raise_faced(self):
        self.assertEqual((self.fold["facing"], self.fold["to_call"], self.fold["pot_if_call"]), ("raise", 6000, 24500))
        self.assertEqual(self.fold["equity_needed"], round(6000 / 24500, 4))
        # The pot before the check-raise and the raise's own chips: 9,500 ÷ (9,500 + 9,000).
        self.assertEqual(self.fold["mdf"], round(9500 / 18500, 4))

    def test_a_bet_against_the_pot_before_it(self):
        self.assertEqual(self.cbet["move"]["size"], round(3000 / 6500, 3))
        self.assertEqual(self.cbet["move"]["pot_before"], 6500)

    def test_position_line_and_holding(self):
        self.assertEqual((self.squeeze["situation"], self.squeeze["callers"]), ("raised", 1))
        line = (self.cbet["position"], self.cbet["preflop"], self.cbet["aggressor"])
        self.assertEqual(line, ("in", "raised", "hero"))
        self.assertEqual((self.cbet["made"], self.cbet["hand_class"], self.cbet["spr"]), ("set", "strong", 2.65))
        self.assertEqual(self.fold["line"], ["bet"])

    def test_hand_classes(self):
        self.assertEqual(hand_class("top_pair"), "strong")
        self.assertEqual(hand_class("second_pair"), "showdown_value")
        self.assertEqual(hand_class("high_card", ["flush_draw"]), "draw")
        self.assertEqual(hand_class("overcards", ["gutshot"]), "nothing")

    def test_the_legal_sizes_agree_with_pokerkit(self):
        rng = random.Random(5)
        for i in range(120):
            seats = [{"seat": 1, "name": "A", "stack": rng.randint(500, 9000)}, {"seat": 2, "name": "B", "stack": 4000}]
            table = TableHand(seats, 1 + i % 2, 50, 100, shuffled_deck(rng))
            while table.actor:
                legal, context = table.legal(), now(table, table.actor)
                with self.subTest(hand=i, events=len(table.replay("A")["events"])):
                    self.assertEqual(context["to_call"], legal["to_call"])
                    sizes = (legal["min_to"], legal["max_to"]) if legal["can_raise"] else None
                    self.assertEqual(context["raise_sizes"] and tuple(context["raise_sizes"]), sizes)
                roll = rng.random()
                if legal["can_raise"] and roll < 0.3:
                    table.act(table.actor, "raise", rng.randint(legal["min_to"], legal["max_to"]))
                else:
                    table.act(table.actor, "check" if legal["can_check"] else "call" if roll < 0.85 else "fold")


class TableTests(SimpleTestCase):
    """practice.table: hands PokerKit deals and checks."""

    def test_a_hand_rebuilds_from_its_deck_and_moves(self):
        deck = shuffled_deck(random.Random(2))
        seats = [{"seat": 1, "name": HERO, "stack": 4000}, {"seat": 2, "name": VILLAIN, "stack": 4000}]
        table = TableHand(seats, 1, 50, 100, deck)
        table.act(HERO, "raise", 250)
        table.act(VILLAIN, "call")

        again = TableHand(seats, 1, 50, 100, deck, table.moves)

        self.assertEqual(again.replay(HERO), table.replay(HERO))
        self.assertEqual(again.cards(VILLAIN), table.cards(VILLAIN))

    def test_the_other_players_cards_stay_hidden_until_shown_down(self):
        table = heads_up(["Ks", "Kd", "Ah", "Qh", "2c", "7c", "8d", "9s"], hero_on_button=True)
        table.act(HERO, "call")
        table.act(VILLAIN, "check")

        seen = table.replay(HERO)

        self.assertEqual([event["player"] for event in seen["events"] if event["type"] == "deal"], [HERO])
        self.assertEqual({player["name"]: player["cards"] for player in seen["players"]}[VILLAIN], [])
        for _ in range(3):
            table.act(VILLAIN, "check")
            table.act(HERO, "check")
        shown = {event["player"]: event["cards"] for event in table.replay(HERO)["events"] if event["type"] == "show"}
        self.assertEqual(shown[VILLAIN], ["Ks", "Kd"])

    def test_moves_the_rules_dont_allow_are_refused(self):
        table = heads_up(hero_on_button=True)
        for name, action, amount in ((VILLAIN, "check", None), (HERO, "check", None), (HERO, "raise", 120)):
            with self.subTest(action=action), self.assertRaises(IllegalMove):
                table.act(name, action, amount)
        self.assertEqual(table.moves, [])

    def test_a_bet_or_raise_is_named_by_what_it_faces(self):
        table = heads_up(hero_on_button=True)
        table.act(HERO, "bet", 250)  # a raise of the big blind, whatever it is called
        table.act(VILLAIN, "call")
        table.act(VILLAIN, "raise", 300)  # the first bet of the flop

        self.assertEqual([move[1] for move in table.moves], ["raise", "call", "bet"])


class RuleTests(SimpleTestCase):
    """practice.rules: the starter playbook's cards on hands played to the spot each is about."""

    def flop(self, cards, villain_bet=None):
        """You in the big blind call a button raise; the flop comes; Villain bets when asked to."""
        table = heads_up(cards)
        table.act(VILLAIN, "raise", 250)
        table.act(HERO, "call")
        if villain_bet:
            table.act(HERO, "check")
            table.act(VILLAIN, "bet", villain_bet)
        return table

    def test_out_of_position_after_calling_a_raise_check_the_flop(self):
        advice = rules.evaluate(now(self.flop(["9c", "4d", "As", "Kd", "2h", "Qs", "8h", "3c"])), RULES)

        self.assertEqual(
            (advice["rule"], advice["action"], advice["verdict"]), ("oop_check_to_raiser", "check", "clear")
        )

    def test_a_bluff_catcher_calls_a_good_price_and_folds_a_bad_one(self):
        cards = ["8c", "4d", "As", "Kd", "2h", "Qs", "8h", "3c"]  # second pair
        good = rules.evaluate(now(self.flop(cards, villain_bet=250)), RULES)
        bad = rules.evaluate(now(self.flop(cards, villain_bet=1500)), RULES)

        self.assertEqual((good["rule"], good["action"], good["verdict"]), ("bluff_catcher_check_call", "call", "clear"))
        # Heads-up, rule 9 won't fold a pair to one bet: the cards disagree, so it is close.
        self.assertEqual((bad["verdict"], bad["conflict"]), ("close", True))
        self.assertEqual(set(bad["rules"]), {"bluff_catcher_check_call", "heads_up_pair_one_bet", "plan_for_all_in"})

    def test_a_draw_calls_when_its_outs_beat_the_price(self):
        cards = ["7h", "6h", "As", "Kd", "2c", "8h", "5h", "Jc"]  # an open-ended straight draw and a flush draw
        cheap = rules.evaluate(now(self.flop(cards, villain_bet=150)), RULES)
        dear = rules.evaluate(now(self.flop(cards, villain_bet=3000)), RULES)

        self.assertEqual((cheap["rule"], cheap["action"], cheap["basis"]), ("price_to_call", "call", "exact"))
        self.assertEqual(cheap["outs"], 15)
        self.assertEqual(dear["action"], "fold")

    def test_a_raise_that_would_fold_to_an_all_in_breaks_rule_7(self):
        context = now(self.flop(["8c", "4d", "As", "Kd", "2h", "Qs", "8h", "3c"], villain_bet=250))

        kept = {result["rule"]: result["followed"] for result in rules.check(context, {"action": "raise"}, RULES)}

        self.assertFalse(kept["plan_for_all_in"])
        self.assertTrue(all(result["followed"] for result in rules.check(context, {"action": "call"}, RULES)))

    def test_on_the_button_raise_every_hand(self):
        advice = rules.evaluate(now(heads_up(["As", "Kd", "7c", "2d"], hero_on_button=True)), RULES)

        self.assertEqual((advice["rule"], advice["action"], advice["to_bb"]), ("button_raise_every_hand", "raise", 2.5))

    def test_a_short_stack_calls_an_all_in_with_any_ace(self):
        table = heads_up(["Ac", "3d", "Kh", "Qh"], stack_bb=12)
        table.act(VILLAIN, "raise", table.legal()["max_to"])

        advice = rules.evaluate(now(table), RULES)

        self.assertEqual((advice["rule"], advice["action"]), ("short_all_in_any_ace", "call"))

    def test_a_sizing_card_is_kept_by_a_bet_of_its_size(self):
        table = heads_up(["Qc", "4d", "As", "Kd", "2h", "Ks", "8h", "3c"], hero_on_button=True)
        table.act(HERO, "raise", 250)
        table.act(VILLAIN, "call")
        table.act(VILLAIN, "check")
        context = now(table)

        half = rules.check(context, {"action": "bet", "size": 0.5}, RULES)
        pot = rules.check(context, {"action": "bet", "size": 1.0}, RULES)

        self.assertEqual(half, [{"rule": "cbet_half_pot", "followed": True}])
        self.assertEqual(pot, [{"rule": "cbet_half_pot", "followed": False}])
        self.assertEqual(rules.evaluate(context, RULES)["size"], 0.5)

    def test_reads_unlock_adjustments_by_degree(self):
        # Top pair called a flop bet; on the turn a second, big bet, which no default card covers.
        table = self.flop(["Qc", "Jd", "Js", "Kd", "2h", "Qs", "8h", "3c", "4d"], villain_bet=250)
        table.act(HERO, "call")
        table.act(HERO, "check")
        table.act(VILLAIN, "bet", 1200)
        context = now(table)
        default = rules.evaluate(context, RULES)
        thin = rules.evaluate(context, RULES, {"big_bets_weak": "thin"})
        strong = rules.evaluate(context, RULES, {"big_bets_weak": "strong"})

        self.assertEqual((default["verdict"], default["basis"]), ("close", "none"))
        self.assertEqual((thin["rule"], thin["verdict"]), ("big_bets_no_credit", "your_call"))
        self.assertEqual(
            (strong["rule"], strong["verdict"], strong["basis"]), ("big_bets_no_credit", "clear", "adjustment")
        )

    def test_outs_and_their_chance(self):
        self.assertEqual(rules.outs(["flush_draw", "open_ended"]), 15)
        self.assertEqual(rules.outs(["nut_flush_draw", "gutshot"]), 12)
        self.assertAlmostEqual(rules.draw_equity(9, 3, all_in=False), 9 / 47)
        self.assertAlmostEqual(rules.draw_equity(9, 3, all_in=True), 0.3497, places=4)  # flop to river

    def test_chen_scores(self):
        scores = {"AsAh": 20, "AhKh": 12, "AhKd": 10, "Ts9s": 8, "2c2d": 5, "7c2d": -1}
        for cards, score in scores.items():
            with self.subTest(cards=cards):
                self.assertEqual(rules.chen([cards[:2], cards[2:]]), score)

    def test_every_card_is_complete(self):
        for playbook in HOUSE.values():
            for rule in playbook["rules"]:
                with self.subTest(rule=rule["id"]):
                    self.assertLessEqual({"id", "number", "family", "kind", "rule", "why", "when", "then"}, set(rule))
                    self.assertTrue(rule["source"])


class QuestionTests(SimpleTestCase):
    def test_the_price_of_a_raise(self):
        hand = hand_in("steals_and_squeezes.txt", "262300000002")
        fold = decisions(hand)[2]

        asked = arithmetic(fold, hand, random.Random(1))

        question, answer = asked["equity_needed"]["question"], asked["equity_needed"]["answer"]
        self.assertEqual(question["options"][answer["correct"]], "24%")
        self.assertEqual(len(set(question["options"])), 4)
        self.assertEqual(asked["mdf"]["question"]["options"][asked["mdf"]["answer"]["correct"]], "51%")
        self.assertEqual(set(asked), {"equity_needed", "pot_odds", "mdf"})

    def test_a_bluff_is_asked_of_a_bet_made(self):
        hand = hand_in("steals_and_squeezes.txt", "262300000002")
        cbet = decisions(hand)[1]

        asked = arithmetic(cbet, hand, random.Random(1))

        self.assertEqual(set(asked), {"bluff_break_even"})
        self.assertAlmostEqual(asked["bluff_break_even"]["answer"]["value"], 3000 / 9500, places=4)

    def test_money_reads_as_the_hand_does(self):
        self.assertEqual(money(1100), "1,100")
        self.assertEqual(money(110, "USD"), "$1.10")
        self.assertEqual(money(200, "EUR"), "€2")


class BotTests(SimpleTestCase):
    def play(self, style, leak, hands=150):
        rng = random.Random(9)
        seen = []
        for i in range(hands):
            seats = [{"seat": 1, "name": "Bot", "stack": 4000}, {"seat": 2, "name": "Other", "stack": 4000}]
            table = TableHand(seats, 1 + i % 2, 50, 100, shuffled_deck(rng))
            while table.actor:
                name = table.actor
                mine = (style, leak) if name == "Bot" else ("tag", None)
                move = bots.decide(now(table, name), table.legal(), *mine, rng)
                table.act(name, *move)
            seen.append(table)
        return seen

    def test_every_style_and_leak_plays_legal_moves(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for style in bots.STYLES:
                self.play(style, None, hands=40)
            for leak in bots.LEAKS:
                self.play("tag", leak, hands=40)

    def test_a_bot_that_raises_every_button_does(self):
        tables = self.play("rock", "raises_every_button")

        first = [table.moves[0] for table in tables if table.button_seat == 1]

        self.assertTrue(all(move[:2] == ["Bot", "raise"] for move in first))


class ProfileBotTests(SimpleTestCase):
    def play(self, profile, seats, hands=60, seed=5):
        """Plays `hands` at a table of `seats`, the first seat by `profile` and the rest tight-aggressive: the share of
        hands the first seat put money in by choice."""
        rng = random.Random(seed)
        played = dealt = 0
        for i in range(hands):
            rows = [{"seat": n, "name": f"P{n}", "stack": 10000} for n in range(1, seats + 1)]
            table = TableHand(rows, 1 + i % seats, 50, 100, shuffled_deck(rng))
            first = None
            while table.actor:
                name = table.actor
                context = now(table, name)
                move = bots.play(context, table.legal(), profile if name == "P1" else bots.PROFILES["tag"], rng)
                if name == "P1" and first is None and context["street"] == "preflop":
                    first = move[0] if context["to_call"] else None
                table.act(name, *move)
            if first:
                dealt += 1
                played += first in ("call", "raise")
        return played / dealt

    def test_every_profile_plays_legal_moves_at_every_size_of_table(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for style, profile in bots.PROFILES.items():
                for seats in (2, 6, 9):
                    with self.subTest(style=style, seats=seats):
                        self.play(profile, seats, hands=25)

    def test_a_loose_profile_plays_more_hands_than_a_tight_one(self):
        self.assertGreater(self.play(bots.PROFILES["lag"], 6), self.play(bots.PROFILES["rock"], 6))

    def test_a_profile_leans_on_a_typical_player_until_its_sample_grows(self):
        few = bots.calibrated({"three_bet_did": 2, "three_bet_could": 2}, {})
        many = bots.calibrated({"three_bet_did": 200, "three_bet_could": 1000}, {})

        typical = bots.PROFILES["tag"]["three_bet"]
        self.assertLess(abs(few["three_bet"] - typical), abs(100 - typical) / 2)  # 2 of 2 says little
        self.assertAlmostEqual(many["three_bet"], 100 * (200 + 15 * typical / 100) / 1015, places=1)

    def test_a_profile_opens_by_seat_from_its_own_counts_there(self):
        profile = bots.calibrated({"rfi_did": 60, "rfi_could": 200}, {"BTN": (45, 50), "UTG": (5, 50)})

        self.assertGreater(profile["rfi"]["BTN"], 70)
        self.assertLess(profile["rfi"]["EP"], 15)
        self.assertEqual(bots.opening("UTG+1", profile), profile["rfi"]["EP"])
        self.assertEqual(bots.opening("BTN", profile, heads_up=True), min(95, profile["rfi"]["BTN"] * 1.8))


class GeneratorTests(SimpleTestCase):
    def test_an_all_in_spot_counts_every_card_to_come(self):
        spot = generators.all_in_spot(random.Random(4))
        context, answer = spot["context"], spot["answer"]

        equity = generators.exact_equity(context["cards"], spot["revealed"][VILLAIN], context["board"])

        self.assertEqual((context["facing"], context["facing_all_in"]), ("bet", True))
        self.assertAlmostEqual(answer["equity"], round(equity, 4))
        calling = (equity * context["pot_if_call"] - context["to_call"]) / generators.BIG_BLIND
        self.assertAlmostEqual(answer["ev_bb"]["call"], round(calling, 2))
        self.assertEqual(answer["best"], ["call" if calling > 0 else "fold"])

    def test_a_push_or_fold_spot_states_its_range_and_its_answer(self):
        spot = generators.push_fold_spot(random.Random(8))
        answer = spot["answer"]

        self.assertIn(answer["range"], [text for text, _ in generators.RANGES.values()])
        self.assertEqual(answer["best"], [max(answer["ev_bb"], key=answer["ev_bb"].get)])
        self.assertTrue(spot["question"]["all_in_only"])

    def test_an_arithmetic_spot_is_a_bet_to_face(self):
        spot = generators.arithmetic_spot(random.Random(3), "mdf")

        self.assertEqual(list(spot["questions"]), ["mdf"])
        self.assertEqual(spot["context"]["facing"], "bet")
        self.assertEqual(spot["hand"]["hero"], HERO)


class ChartTests(SimpleTestCase):
    def test_each_seat_plays_its_tier_and_moves_up_one_facing_a_raise(self):
        self.assertEqual(charts.tier_for("UTG+2"), "early")
        self.assertEqual(charts.tier_for("HJ"), "middle")
        self.assertEqual(charts.tier_for("HJ", facing_raise=True), "early")
        # The lecture names no tier above early position's, nor any range from the cutoff on.
        self.assertIsNone(charts.tier_for("UTG", facing_raise=True))
        self.assertIsNone(charts.tier_for("CO"))

    def test_a_tier_shows_its_exact_share_beside_the_lectures(self):
        early, middle = charts.chart_of("early"), charts.chart_of("middle")

        self.assertEqual((early["claimed"], early["share"]), ("about the top 5%", round(50 / 1326, 4)))
        self.assertEqual((middle["claimed"], middle["share"]), ("about the top 15%", round(106 / 1326, 4)))

    def test_the_chart_raises_its_hands_and_folds_the_rest(self):
        raised = {"best": ["raise"], "acceptable": ["call"], "in_range": True}
        self.assertEqual(charts.answer("AJo", "middle", False), raised)
        self.assertEqual(charts.answer("A9s", "middle", False)["best"], ["fold"])
        self.assertEqual(charts.answer("AQs", "early", True)["best"], ["raise", "call"])
        self.assertEqual(charts.answer("AQo", "early", True)["best"], ["fold"])

    def test_a_range_answer_scores_its_overlap_by_combos(self):
        tens = ranges.parse("TT+")  # 30 combos

        self.assertEqual(charts.overlap_score(tens, tens), 1.0)
        self.assertEqual(charts.overlap_score(ranges.parse("22-55"), tens), 0.0)
        self.assertAlmostEqual(charts.overlap_score(ranges.parse("JJ+"), tens), 24 / 30)
        self.assertEqual(charts.overlap(ranges.parse("99+"), tens), {"both": 30, "extra": 6, "missed": 0})
        self.assertEqual([charts.range_grade(score) for score in (0.8, 0.5, 0.2)], ["good", "acceptable", "poor"])

    def test_ranges_round_trip_through_notation(self):
        rng = random.Random(2)
        for _ in range(200):
            hands = set(rng.sample(ranges.HANDS, rng.randint(1, 169)))
            with self.subTest(hands=sorted(hands)):
                self.assertEqual(ranges.parse(ranges.notation(hands)), hands)
        self.assertEqual(ranges.notation(ranges.parse("TT+, AQs+, AKo")), "TT+, AQs+, AKo")
        self.assertEqual(ranges.notation(ranges.HANDS), "any")


class FullTableGeneratorTests(SimpleTestCase):
    def test_an_open_is_folded_to_you_at_a_full_table_in_the_value_zone(self):
        for seed in range(12):
            spot = generators.preflop_spot(random.Random(seed), facing=False)
            context, answer = spot["context"], spot["answer"]
            with self.subTest(seed=seed):
                self.assertEqual((context["players_dealt"], context["situation"]), (9, "unopened"))
                self.assertIn(context["hero_position"], charts.SEATS)
                self.assertTrue(spot["hand"]["tournament_id"])
                tier = charts.tier_for(context["hero_position"])
                self.assertEqual(answer["chart"]["tier"], tier)
                self.assertEqual(answer["in_range"], answer["hand"] in charts.hands_of(tier))
                self.assertEqual(ranges.combo_of(context["cards"]), answer["hand"])

    def test_facing_a_raise_moves_up_a_tier(self):
        spot = generators.preflop_spot(random.Random(3), facing=True)
        context = spot["context"]

        self.assertIn(context["hero_position"], ("LJ", "HJ"))
        self.assertEqual(context["situation"], "raised")
        self.assertEqual(spot["answer"]["chart"]["tier"], "early")

    def test_a_range_read_names_its_line_and_answers_with_the_top_share(self):
        for seed in range(8):
            spot = generators.range_read_spot(random.Random(seed))
            answer = spot["answer"]
            with self.subTest(seed=seed):
                self.assertEqual(spot["question"]["kind"], "range")
                self.assertIn(f"{answer['percent']}%", spot["question"]["prompt"])
                self.assertEqual(ranges.parse(answer["range"]), ranges.top(answer["percent"]))
                self.assertIn(spot["context"]["situation"], ("raised", "3bet"))


class ChartGradingTests(SimpleTestCase):
    @staticmethod
    def scenario(kind, grading, answer):
        return SimpleNamespace(spec={"question": {"kind": kind}}, grading=grading, answer=answer)

    def test_a_chart_grades_the_move_and_half_credits_a_limp(self):
        spot = self.scenario("action", "reference", charts.answer("AJo", "middle", False))

        self.assertEqual(sets.grade(spot, {"action": "raise", "amount": 500})["grade"], "good")
        self.assertEqual(sets.grade(spot, {"action": "call"})["score"], 0.5)
        self.assertEqual(sets.grade(spot, {"action": "fold"})["grade"], "poor")

    def test_a_range_earns_its_overlap(self):
        spot = self.scenario("range", "reference", {"range": "TT+"})

        self.assertEqual(sets.grade(spot, {"hand_range": "TT+"}), {"grade": "good", "score": 1.0, "weight": 1.0})
        self.assertEqual(sets.grade(spot, {"hand_range": "JJ+"})["score"], 0.8)
        self.assertEqual(sets.grade(spot, {"hand_range": ""})["grade"], "poor")


class LibraryTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(library, "EQUITY_SAMPLES", 3000)  # sampled once per entry: quicker, looser
        patcher.start()
        self.addCleanup(patcher.stop)

    def answer_of(self, key):
        entry = library.build(key)
        question, answer = entry["question"], entry["answer"]
        return entry, question["options"][answer["correct"]] if question["kind"] == "choice" else answer["best"]

    def test_every_entry_builds_and_credits_its_lecture(self):
        for key, (_, source, skills, _, _) in library.ENTRIES.items():
            with self.subTest(key=key):
                entry = library.build(key)
                self.assertTrue(entry["answer"]["explanation"].endswith(f"[{source}]"))
                self.assertIn(entry["grading"], ("exact", "rule"))
                self.assertEqual(entry["skills"], skills)
                self.assertEqual(entry["hand"] is None, bool(entry["setup"]))

    def test_the_lectures_numbers(self):
        expected = {
            "pot_odds_share": "17%",
            "pot_odds_ratio": "10.0 : 1",
            "mdf_half_pot": "67%",
            "bluff_two_thirds": "40%",
            "ev_flush_draw": "−$2",
            "m_big_blind_ante": "3.0",
            "set_odds": "7.5 : 1",
            "rule_of_four": "35%",
            "akq_king_calls": "67%",
            "akq_queen_bluffs": "33%",
            "icm_flip": "$766.67",
            "satellite_aces": "Fold",
            "heads_up_calling": "40%",
        }
        for key, right in expected.items():
            with self.subTest(key=key):
                self.assertEqual(self.answer_of(key)[1], right)

    def test_any_two_cards_beat_folding_at_m_2_5(self):
        entry, best = self.answer_of("push_any_two")
        context = entry["context"]

        self.assertEqual(best, ["raise"])
        self.assertEqual((context["hero_position"], context["cards"]), ("SB", ["9d", "6c"]))
        self.assertGreater(entry["answer"]["ev_bb"]["raise"], entry["answer"]["ev_bb"]["fold"])

    def test_spots_at_a_table_are_dealt_as_the_lecture_tells_them(self):
        pot_odds = library.build("pot_odds_share")["context"]
        self.assertEqual((pot_odds["bet"], pot_odds["pot_before"], pot_odds["to_call"]), (10000, 38000, 10000))
        draw = library.build("ev_flush_draw")
        self.assertEqual((draw["context"]["to_call"], draw["context"]["pot_if_call"]), (2000, 9000))
        self.assertIn("flush_draw", draw["context"]["draws"])
        m = library.build("m_big_blind_ante")["hand"]
        antes = [event for event in m["events"] if event.get("blind") == "ante"]
        self.assertEqual([(event["player"], event["amount"]) for event in antes], [("BB", 4000)])


class RatingTests(SimpleTestCase):
    def test_a_win_raises_a_rating_and_narrows_its_range(self):
        rating, deviation = ratings.update(1500, 350, 1500, 350, 1.0)
        lost, _ = ratings.update(1500, 350, 1500, 350, 0.0)

        self.assertGreater(rating, 1500)
        self.assertLess(deviation, 350)
        self.assertAlmostEqual(rating - 1500, 1500 - lost)

    def test_half_weight_moves_it_half_as_far(self):
        full, full_deviation = ratings.update(1500, 200, 1600, 100, 1.0)
        half, half_deviation = ratings.update(1500, 200, 1600, 100, 1.0, weight=0.5)

        self.assertAlmostEqual(half - 1500, (full - 1500) / 2)
        self.assertGreater(half_deviation, full_deviation)
        self.assertLess(half_deviation, 200)

    def test_glickmans_example(self):
        # Glickman's paper: 1500 ± 200 against 1400 ± 30, 1550 ± 100 and 1700 ± 300 as one rating period gives
        # 1464 ± 151.4; one game at a time it ends close to that.
        rating, deviation = 1500, 200
        for other, spread, score in ((1400, 30, 1), (1550, 100, 0), (1700, 300, 0)):
            rating, deviation = ratings.update(rating, deviation, other, spread, score)

        self.assertAlmostEqual(rating, 1464, delta=6)
        self.assertAlmostEqual(deviation, 151.4, delta=3)

    def test_time_away_widens_a_range_up_to_where_it_started(self):
        self.assertEqual(ratings.widened(50, 0), 50)
        self.assertGreater(ratings.widened(50, 30), 50)
        self.assertEqual(ratings.widened(50, 10_000), ratings.START_DEVIATION)
        self.assertEqual(ratings.interval(1500, 100), (1304, 1696))
