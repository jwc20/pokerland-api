"""The library: worked examples from the lectures, as spots to practise (pokerland-practice-mode.md, 3.4 and 4.3).

Each entry is one of the lectures' own examples, as Appendix B of the feature ideas records it, worked into a spot:
the same numbers, the same answer, credited to its lecture. Every answer is exact, from inputs stated with the spot,
except the course's heads-up calling rule, which is a rule of thumb and counts half.

Most entries are dealt at a practice table, so they look like any other spot; the toy game and the prize-pool
questions have no table, only their setup in words. Where an example needs a hand the lecture doesn't give (the cards
behind a flush draw, the stacks around an M), the spot picks one that changes nothing in the arithmetic.

Spots from well-known hands, written up from their public accounts, belong here too: credited, as facts rather than
footage, and checked for rights before shipping (4.3 there). None are written up yet.

Django-free, like practice.generators. `build(key)` makes one entry's spot; practice.sets saves each once.
"""

import random
from math import comb

from pokerkit.analysis import calculate_icm

from hands import ranges
from practice import generators
from practice.questions import arithmetic
from practice.spots import pending
from practice.table import TableHand
from tracker.parsing.equity import range_share

VERSION = 1
HERO, VILLAIN = generators.HERO, generators.VILLAIN
GAME = "Hold'em No Limit"
EQUITY_SAMPLES = 20000  # once per entry, when it is first saved


def build(key):
    """One library entry's spot: {"key", "title", "source", "skills", "tier", "grading", "topic", "hand" (None for no
    table), "setup", "question", "answer", "context"}."""
    title, source, skills, tier, make = ENTRIES[key]
    found = make(random.Random(key))
    found["answer"]["explanation"] = f"{found['answer']['explanation']} [{source}]"
    return {
        "key": key,
        "title": title,
        "source": source,
        "skills": skills,
        "tier": tier,
        "grading": found.pop("grading", "exact"),
        "setup": found.pop("setup", ""),
        "context": found.get("context"),
        **found,
    }


# Spots at a table ------------------------------------------------------------------------------------------------


def _heads_up(rng, blinds, stack, hero_on_button=False, first=()):
    seats = [{"seat": 1, "name": HERO, "stack": stack}, {"seat": 2, "name": VILLAIN, "stack": stack}]
    small, big = blinds
    return TableHand(seats, 1 if hero_on_button else 2, small, big, generators.deck(rng, first))


def _spot(table, currency="", tournament=False):
    """The hand up to your decision, as you see it, with its context."""
    hand = {
        **table.replay(HERO),
        "game": GAME,
        "currency": currency,
        "tournament_id": "library" if tournament else "",
    }
    return {"hand": hand, "context": pending(hand)}


def _raised_pot(rng, blinds, raise_to, currency="USD", stack=100000):
    """Heads-up: Villain raises on the button, you call in the big blind and check the flop to them."""
    table = _heads_up(rng, blinds, stack)
    table.act(VILLAIN, "raise", raise_to)
    table.act(HERO, "call")
    table.act(HERO, "check")
    return table


def _asked(found, topic, rng):
    """One of practice.questions' arithmetic questions about a spot."""
    asked = arithmetic(found["context"], found["hand"], rng)[topic]
    return {**found, "topic": topic, "question": asked["question"], "answer": asked["answer"]}


def pot_odds_share(rng):
    """Facing $100 with $380 in the pot: 100 ÷ 580 ≈ 17% [MIT 3]."""
    table = _raised_pot(rng, (500, 1000), 19000)
    table.act(VILLAIN, "bet", 10000)
    return _asked(_spot(table, "USD"), "equity_needed", rng)


def pot_odds_ratio(rng):
    """$180 in the pot, a $20 bet: 200 : 20 = 10 : 1 [JHU 2]."""
    table = _raised_pot(rng, (100, 200), 9000)
    table.act(VILLAIN, "bet", 2000)
    return _asked(_spot(table, "USD"), "pot_odds", rng)


def mdf_half_pot(rng):
    """Against a half-pot bet, defend 1 ÷ (1 + ½) = 67% [MIT 7; MIT 8]."""
    table = _raised_pot(rng, (100, 200), 5000)
    table.act(VILLAIN, "bet", 5000)
    return _asked(_spot(table, "USD"), "mdf", rng)


def bluff_two_thirds(rng):
    """A two-thirds-pot bluff must work 40% of the time [MIT 3]."""
    table = _heads_up(rng, (50, 100), 10000, hero_on_button=True)
    table.act(HERO, "raise", 225)
    table.act(VILLAIN, "call")
    table.act(VILLAIN, "check")
    found = _spot(table)
    pot = found["context"]["pot"]
    found["context"]["move"] = {"action": "bet", "amount": pot * 2 // 3, "pot_before": pot, "size": 2 / 3}
    return _asked(found, "bluff_break_even", rng)


def ev_flush_draw(rng):
    """Calling $20 to win $70 with a 20% flush draw: 0.2 × 70 − 0.8 × 20 = −$2 [MIT 3; JHU 2]."""
    # You in the big blind with a flush draw, Villain on the button with top pair; burns between the streets.
    first = ["Qh", "3h", "Ks", "Td", "4c", "Kh", "9h", "2c", "5d", "7s"]
    table = _heads_up(rng, (100, 200), 100000, first=first)
    table.act(VILLAIN, "raise", 2500)
    table.act(HERO, "call")
    table.act(HERO, "check")
    table.act(VILLAIN, "check")
    table.act(HERO, "check")
    table.act(VILLAIN, "bet", 2000)
    found = _spot(table, "USD")
    options = ["−$2", "+$2", "+$14", "−$6"]
    rng.shuffle(options)
    found.update(
        topic="ev_of_a_call",
        question={
            "kind": "choice",
            "prompt": "Calling $20 wins the $70 in the middle, and your flush draw comes in 20% of the time. "
            "What is the call worth?",
            "options": options,
        },
        answer={
            "correct": options.index("−$2"),
            "value": -2.0,
            "formula": "P(win) × amount won − P(lose) × amount lost",
            "explanation": (
                "0.2 × $70 − 0.8 × $20 = $14 − $16 = −$2: fold. The 9 outs come 9 times in 46 on the river, 19.6%, "
                "so the lecture's 20% is about right."
            ),
        },
    )
    return found


def m_big_blind_ante(rng):
    """30,000 chips at 2,000 / 4,000 with a 4,000 big-blind ante: M = 3 [MIT 1; JHU 6]."""
    cards = rng.choice(ranges.holdings(rng.choice(ranges.RANKING)))

    def stack(name):
        return 30000 if name == HERO else rng.randrange(40, 150) * 1000

    table = generators.full_table(rng, 9, "CO", cards, stack, (2000, 4000), ante={"BB": 4000})
    while table.actor != HERO:
        table.act(table.actor, "fold")
    return _asked(_spot(table, tournament=True), "m", rng)


def push_any_two(rng):
    """With an M around 2.5 in the small blind, moving in with any two cards beats folding, whatever the big blind
    calls with: 9-6 offsuit is the lecture's example [MIT 4]."""
    small, big, ante = 100, 200, 25

    def stack(name):
        return 1300 if name == HERO else 9000

    cards = ["9d", "6c"]
    table = generators.full_table(rng, 9, "SB", cards, stack, (small, big), ante)
    while table.actor != HERO:
        table.act(table.actor, "fold")
    found = _spot(table, tournament=True)
    # Folding gives up the small blind and the ante; a shove the big blind folds to wins the big blind and the others'
    # antes; called, you play for both stacks and the antes of the seven who folded.
    fold = -(small + ante) / big
    won = (big + 8 * ante) / big
    pot = 2 * 1300 + 7 * ante
    rows = []
    for percent in (5, 10, 20, 30, 50, 100):
        combos = [combo for hand in ranges.top(percent) for combo in ranges.holdings(hand, dead=cards)]
        equity, _ = range_share(cards, combos, rng=rng, samples=EQUITY_SAMPLES)
        share = len(combos) / comb(50, 2)
        rows.append((percent, (1 - share) * won + share * (equity * pot - 1300) / big))
    worst = min(value for _, value in rows)
    named = ", ".join(f"the top {percent}%: {value:+.2f} bb" for percent, value in rows if percent < 100)
    found.update(
        topic="push_fold",
        question={
            "kind": "action",
            "prompt": "Folded to you in the small blind with 9-6 offsuit and an M of about 2.5. Move in or fold?",
            "all_in_only": True,
        },
        answer={
            "best": ["raise"],
            "ev_bb": {"raise": round(worst, 2), "fold": round(fold, 2)},
            "assumptions": "The big blind calls with any range, from the top 5% of hands to any two cards; the EV "
            "shown for moving in is against the range worst for you.",
            "explanation": (
                f"Moving in is worth more than folding, {fold:+.2f} bb, whatever the big blind calls with: against "
                f"{named}, and against any two cards {rows[-1][1]:+.2f} bb. The blinds and antes are a big share "
                "of your stack, and every fold wins them."
            ),
        },
    )
    return found


# Spots without a table: the toy game and the prize pool ---------------------------------------------------------


def _choice(rng, setup, prompt, options, correct, explanation, topic, formula=None, value=None):
    shuffled = list(options)
    rng.shuffle(shuffled)
    answer = {"correct": shuffled.index(options[correct]), "explanation": explanation}
    if formula:
        answer["formula"] = formula
    if value is not None:
        answer["value"] = value
    return {
        "hand": None,
        "context": None,
        "setup": setup,
        "topic": topic,
        "question": {"kind": "choice", "prompt": prompt, "options": shuffled},
        "answer": answer,
    }


AKQ_SETUP = (
    "The AKQ game: a deck of three cards, the ace, the king and the queen. Each player antes 1 and is dealt one card. "
    "The first player may bet 1 or check; facing a bet, the second may call or fold. The higher card wins."
)


def akq_king_calls(rng):
    """The AKQ game: the king calls a bet 2 ÷ 3 of the time, the minimum defense frequency [MIT 8]."""
    return _choice(
        rng,
        AKQ_SETUP,
        "You are second, with the king, facing a bet of 1 into the pot of 2. How often must you call so that a bluff "
        "with the queen can't profit?",
        ["67%", "50%", "33%", "100%"],
        0,
        "A bluff risks 1 to win the pot of 2, so it profits if you fold more than 1 time in 3: call 2 times in 3. "
        "That is the minimum defense frequency, pot ÷ (pot + bet) = 2 ÷ 3.",
        "akq_call",
        formula="pot ÷ (pot + bet)",
        value=2 / 3,
    )


def akq_queen_bluffs(rng):
    """The AKQ game: the queen bluffs a third as often as the ace bets [MIT 8]."""
    return _choice(
        rng,
        AKQ_SETUP,
        "You are first, with the queen. You bet the ace every time. How often should you bluff with the queen so "
        "that the king does as well calling as folding?",
        ["33%", "50%", "25%", "67%"],
        0,
        "Calling with the king wins 3, the pot and your bet, against a bluff, and loses 1 against the ace. It breaks "
        "even when bluffs are a third of your value bets: bluffs = value bets × s ÷ (1 + s), with s = 1 ÷ 2 the bet "
        "as a share of the pot. So bluff a third of your queens; a quarter of your bets are then bluffs.",
        "akq_bluff",
        formula="value bets × s ÷ (1 + s)",
        value=1 / 3,
    )


def icm_flip(rng):
    """Four stacks of 2,500 paying 1,000 / 600 / 400: the flip winner goes from $500 to $766.67 [MIT 5]."""
    winner, survivor = calculate_icm([1000, 600, 400], [5000, 2500, 2500, 0])[:2]
    return _choice(
        rng,
        "Four players are left in a tournament paying $1,000, $600 and $400, each with 2,500 chips: $500 of prize "
        "equity apiece. Two of them play a hand for all their chips.",
        "By ICM, what is the winner's prize equity after the hand?",
        [f"${winner:,.2f}", "$1,000.00", "$650.00", "$533.33"],
        0,
        f"ICM, the Malmuth–Harville model, values chips by the chance of each finish they give. Doubling to 5,000 of "
        f"the 10,000 chips takes the winner from $500 to ${winner:,.2f}, up ${winner - 500:,.2f}; each player still in "
        f"goes to ${survivor:,.2f}. A chip chop would give the winner $1,000: chips are worth less the more you have.",
        "icm",
        value=round(winner, 2),
    )


def satellite_aces(rng):
    """With flat payouts, fold even aces to a shove one place off the money [MIT 5]."""
    stacks = [3000, 4000, 2500, 500]
    hero = ["As", "Ah"]
    combos = [combo for hand in ranges.HANDS for combo in ranges.holdings(hand, dead=hero)]
    equity, _ = range_share(hero, combos, rng=rng, samples=EQUITY_SAMPLES)
    seats = [1, 1, 1]
    fold = calculate_icm(seats, stacks)[0]
    winning = calculate_icm(seats, [6000, 1000, 2500, 500])[0]
    call = equity * winning
    return _choice(
        rng,
        "A satellite with four players left and three seats to win, each worth the same. You have 3,000 chips; the "
        "others have 4,000, 2,500 and 500. The 4,000 stack moves all-in with any two cards, and it is folded to you "
        "with A♠ A♥.",
        "Call or fold?",
        ["Fold", "Call"],
        0,
        f"Only a seat pays, so what counts is surviving. Folding keeps {fold:.1%} of a seat by ICM. Calling wins "
        f"{equity:.0%} of the time, holding {winning:.1%} of a seat then, but busts you the rest: {call:.1%} of a "
        "seat in all. With flat payouts, fold even aces one place off the money. The blinds are left out.",
        "icm",
        value=round(fold - call, 4),
    )


def heads_up_calling(rng):
    """Heads-up, call twice the pushing share at M 2: he pushes 20%, call with 40% [MIT 4]."""
    found = _choice(
        rng,
        "Heads-up near the end of a tournament. Your M is 2, and your opponent moves all-in with about 20% of hands.",
        "By the course's heads-up calling rule, with what share of hands do you call?",
        ["40%", "20%", "10%", "80%"],
        0,
        "At M 2 call with twice his pushing share: 40%. At M 1 call almost always; at M 4 with the same share; at M 6 "
        "two-thirds of it; at M 9 half. It is a rule of thumb, so it counts half.",
        "calling_rule",
    )
    found["grading"] = "rule"
    return found


def set_odds(rng):
    """7.5 : 1 against flopping a set or better with a pocket pair, 11.8% [JHU 3; JHU 4]."""
    hit = 1 - comb(48, 3) / comb(50, 3)
    against = (1 - hit) / hit
    return _choice(
        rng,
        "You hold a pocket pair before the flop.",
        "What are the odds against flopping a set or better?",
        [f"{against:.1f} : 1", "4.2 : 1", "11.5 : 1", "15 : 1"],
        0,
        f"Two cards of your rank are left among the 50 you can't see. The flop misses both C(48, 3) ÷ C(50, 3) of the "
        f"time, so it brings one {hit:.1%} of the time: {against:.1f} : 1 against.",
        "set_odds",
        formula="1 − C(48, 3) ÷ C(50, 3)",
        value=round(against, 2),
    )


def rule_of_four(rng):
    """9 outs from the flop to the river: about 36% by the rule of 4, exactly 35.0% [MIT 3; JHU 7]."""
    exact = 1 - (38 / 47) * (37 / 46)
    return _choice(
        rng,
        "You hold A♥ 7♥ on a flop of K♥ 9♥ 2♣: a flush draw, 9 outs, against a better hand. You are all-in, so you "
        "see both the turn and the river.",
        "How often does the flush come in?",
        [f"{exact:.0%}", "19%", "45%", "27%"],
        0,
        f"The rule of 4: 9 outs × 4 ≈ 36%. Exactly, both cards miss 38 ÷ 47 × 37 ÷ 46 of the time, so it comes "
        f"{exact:.1%}. One card to come is half that, about 19%.",
        "rule_of_four",
        formula="1 − (38 ÷ 47) × (37 ÷ 46)",
        value=round(exact, 4),
    )


def deny_the_draw(rng):
    """Against a 9-out draw at 4.1 : 1, bet more than about a third of the pot [JHU 2]."""
    against = 37 / 9
    least = 1 / (against - 1)
    return _choice(
        rng,
        "On the turn your opponent has a flush draw, 9 outs, with one card to come, and you have the best hand.",
        "What is the smallest of these bets that denies the draw the price to call?",
        ["A third of the pot", "A quarter of the pot", "Half the pot", "The whole pot"],
        0,
        f"The draw comes 9 times in 46: {against:.1f} : 1 against. A call pays when the pot lays more than that, so "
        f"bet more than pot ÷ ({against:.1f} − 1) = {least:.0%} of the pot. A third is the least of these that does; "
        "half to three quarters leaves room for the money the draw wins later.",
        "deny_draw",
        formula="pot ÷ (odds against − 1)",
        value=round(least, 4),
    )


# key: (title, source, skills, tier, builder)
ENTRIES = {
    "pot_odds_share": ("Pot odds as a share", "MIT 3", ["arithmetic"], 1, pot_odds_share),
    "pot_odds_ratio": ("Pot odds as a ratio", "JHU 2", ["arithmetic"], 1, pot_odds_ratio),
    "mdf_half_pot": ("Defending against half the pot", "MIT 7; MIT 8", ["arithmetic"], 1, mdf_half_pot),
    "bluff_two_thirds": ("A two-thirds-pot bluff", "MIT 3", ["arithmetic"], 1, bluff_two_thirds),
    "ev_flush_draw": ("The EV of calling with a draw", "MIT 3; JHU 2", ["arithmetic"], 2, ev_flush_draw),
    "m_big_blind_ante": ("Harrington's M with a big-blind ante", "MIT 1; JHU 6", ["arithmetic"], 2, m_big_blind_ante),
    "set_odds": ("Flopping a set", "JHU 3; JHU 4", ["arithmetic"], 1, set_odds),
    "rule_of_four": ("The rule of 2 and 4", "MIT 3; JHU 7", ["arithmetic"], 1, rule_of_four),
    "deny_the_draw": ("Denying a draw its price", "JHU 2", ["postflop"], 2, deny_the_draw),
    "akq_king_calls": ("The AKQ game: the king's calls", "MIT 8", ["postflop"], 3, akq_king_calls),
    "akq_queen_bluffs": ("The AKQ game: the queen's bluffs", "MIT 8", ["postflop"], 3, akq_queen_bluffs),
    "push_any_two": ("Any two cards at M 2.5", "MIT 4", ["push_fold"], 2, push_any_two),
    "heads_up_calling": ("The heads-up calling rule", "MIT 4", ["push_fold"], 2, heads_up_calling),
    "icm_flip": ("Chips and prizes: a flip four-handed", "MIT 5", ["push_fold"], 3, icm_flip),
    "satellite_aces": ("A satellite's bubble", "MIT 5", ["push_fold"], 3, satellite_aces),
}
