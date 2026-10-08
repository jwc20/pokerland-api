"""The practice engines on their own: spots, the playbook's rules, questions, the table, the bots, the generators.

No database: like tracker.parsing they run on fixture files and on hands played here.
"""

import random
import warnings

from django.test import SimpleTestCase

from practice import bots, generators, rules
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
