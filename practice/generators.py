"""Fresh spots for one skill, played out by PokerKit so every one is a legal state (pokerland-practice-mode.md, 4.4).

Each generator deals a hand at practice.table, plays it to a decision, and writes the question with its answer and
how the answer was derived:

- `arithmetic_spot`: a bet to face, or one of yours to size up, and the numbers behind it (practice.questions).
  Exact.
- `all_in_spot`: an all-in on the flop or turn from a hand that is shown, against your draw; call or fold. Exact:
  every card to come is counted.
- `push_fold_spot`: a short stack, shove or fold in the small blind, or call or fold in the big blind, against a
  range stated with the spot [MIT 4; JHU 6]. Exact chip EV against that range; the equity is sampled, so a spot
  too close for the sample to settle is dealt again.
- `preflop_spot`: a full table in a tournament's value zone, folded to you in early or middle position, or a raise
  in front of you from the hijack or lojack: graded by the MIT course's chart (practice.charts) [MIT 5].
- `range_read_spot`: a player opens, or re-raises your open, with a share of hands stated with the spot: which
  hands are those? Graded by overlap with that share of hands at the top of the ranking [MIT 4].

The heads-up players are "You" and "Villain"; at a full table the others go by their seats. The table labels them
by position. Django-free, like practice.table.
"""

import math

from pokerkit import Deck
from pokerkit.analysis import parse_range

from hands import ranges
from practice import charts
from practice.questions import arithmetic
from practice.spots import STRONG_DRAWS, pending, postflop_order
from practice.table import TableHand
from tracker.parsing.equity import range_share, shares, value
from tracker.parsing.facts import draws, made_hand
from tracker.parsing.pokerstars import positions

HERO, VILLAIN = "You", "Villain"
SMALL_BLIND, BIG_BLIND = 50, 100
# Stated ranges, as the MIT course's memory aids put them [MIT 4]; the share of hands each holds is about right.
RANGES = {
    "top_5": ("TT+, AQ+", "tens or better and ace-queen or better, about the top 5%"),
    "aces_pairs": ("22+, A2+", "any pair or any ace, about the top 20%"),
    "broadway": ("22+, A2+, KT+, QT+, JT", "any pair, any ace or two Broadway cards, about the top 30%"),
    "any": ("22+, A2+, K2+, Q2+, J2+, T2+, 92+, 82+, 72+, 62+, 52+, 42+, 32", "any two cards"),
}
SAMPLES = 4000
BET_SIZES = (0.25, 0.33, 0.5, 0.66, 0.75, 1.0, 1.5)
CARDS = [repr(card) for card in Deck.STANDARD]


def deck(rng, first=()):
    """A shuffled deck that deals `first` first: the big blind's two cards, the button's two, then a burn and the
    flop, a burn and the turn."""
    rest = [card for card in CARDS if card not in first]
    rng.shuffle(rest)
    return "".join([*first, *rest])


def table(rng, stack_bb, hero_on_button, first=()):
    """A heads-up hand with "You" in seat 1 and "Villain" in seat 2, both `stack_bb` deep."""
    stack = round(stack_bb * BIG_BLIND)
    seats = [{"seat": 1, "name": HERO, "stack": stack}, {"seat": 2, "name": VILLAIN, "stack": stack}]
    return TableHand(seats, 1 if hero_on_button else 2, SMALL_BLIND, BIG_BLIND, deck(rng, first))


def spot(hand_table, tournament=False, **fields):
    """The hand up to your decision, as you see it, with the decision's context."""
    tournament_id = "practice" if tournament else ""
    hand = {**hand_table.replay(HERO), "game": "Hold'em No Limit", "currency": "", "tournament_id": tournament_id}
    return {"hand": hand, "context": pending(hand), **fields}


def arithmetic_spot(rng, topic=None):
    """A bet from the button to the big blind on the flop, turn or river; or, for a bluff's question, a bet of yours.

    Returns the spot and the questions practice.questions asks of it: every one it can, or `topic`'s alone.
    """
    yours = topic == "bluff_break_even" or (topic is None and rng.random() < 0.25)
    hand = table(rng, rng.choice((40, 60, 100, 100, 150)), hero_on_button=yours)
    button, blind = (HERO, VILLAIN) if yours else (VILLAIN, HERO)
    hand.act(button, "raise", rng.choice((200, 250, 300)))
    hand.act(blind, "call")
    for _ in range(rng.choice((0, 0, 0, 1, 1, 2))):  # checked through to a later street
        hand.act(blind, "check")
        hand.act(button, "check")
    hand.act(blind, "check")
    if yours:
        found = spot(hand)
        pot = found["context"]["pot"]
        amount = max(BIG_BLIND, round(pot * rng.choice(BET_SIZES)))
        found["context"]["move"] = {"action": "bet", "amount": amount, "pot_before": pot, "size": amount / pot}
    else:
        pot = pending(hand.replay(VILLAIN))["pot"]
        hand.act(VILLAIN, "bet", max(BIG_BLIND, round(pot * rng.choice(BET_SIZES))))
        found = spot(hand)
    asked = arithmetic(found["context"], found["hand"], rng)
    found["questions"] = {topic: asked[topic]} if topic in asked else {} if topic else asked
    return found


def all_in_spot(rng):
    """Villain moves all-in on the flop or turn and shows a hand that is ahead of your draw. Call or fold?

    The answer counts every card to come: your equity, and the EV of calling against folding in big blinds.
    """
    while True:
        cards = list(CARDS)
        rng.shuffle(cards)
        yours, theirs, board = cards[:2], cards[2:4], cards[4 : 4 + rng.choice((3, 4))]
        if _rank(theirs, board) > _rank(yours, board) and _drawing(yours, board):
            break
    burns = cards[8:10]
    first = [*theirs, *yours, burns[0], *board[:3], *([burns[1], board[3]] if len(board) == 4 else [])]
    # The shove is half the pot to twice it: 5 bb in the middle on the flop, 10 on the turn.
    put_in, pot = (2.5, 5) if len(board) == 3 else (5, 10)
    hand = table(rng, put_in + pot * rng.choice((0.5, 0.75, 1, 1.5, 2)), hero_on_button=True, first=first)
    hand.act(HERO, "raise", 250)
    hand.act(VILLAIN, "call")
    if len(board) == 4:
        hand.act(VILLAIN, "check")
        hand.act(HERO, "bet", 250)
        hand.act(VILLAIN, "call")
    hand.act(VILLAIN, "bet", hand.legal()["max_to"])
    found = spot(hand, revealed={VILLAIN: theirs})
    context = found["context"]
    equity = exact_equity(yours, theirs, context["board"])
    to_call, pot = context["to_call"], context["pot_if_call"]
    calling = (equity * pot - to_call) / BIG_BLIND
    found.update(
        topic="all_in_call",
        question={"kind": "action", "prompt": f"{VILLAIN} moves all-in and shows their hand. Call or fold?"},
        answer={
            "best": ["call" if calling > 0 else "fold"],
            "ev_bb": {"call": round(calling, 2), "fold": 0.0},
            "equity": round(equity, 4),
            "equity_needed": round(to_call / pot, 4),
            "assumptions": f"{VILLAIN} shows {' '.join(theirs)}, and every card to come is counted.",
            "explanation": (
                f"You win {equity:.1%} of the run-outs, ties counting half, and need {to_call / pot:.1%}: "
                f"calling is worth {calling:+.2f} bb against folding."
            ),
        },
    )
    return found


def push_fold_spot(rng):
    """A short stack heads-up: shove or fold in the small blind, or call or fold against a shove in the big blind."""
    while True:
        calling = rng.random() < 0.5
        key = rng.choice(("aces_pairs", "broadway", "any") if calling else ("top_5", "aces_pairs", "broadway"))
        if found := _push_fold(rng, rng.choice((5, 6, 8, 10, 12, 15)), calling, key):
            return found


def _push_fold(rng, stack_bb, calling, key):
    hand = table(rng, stack_bb, hero_on_button=not calling)
    if calling:
        hand.act(VILLAIN, "raise", hand.legal()["max_to"])
    found = spot(hand)
    yours = found["context"]["cards"]
    text, described = RANGES[key]
    theirs = [combo for combo in parse_range(text) if not {repr(card) for card in combo} & set(yours)]
    share = len(theirs) / math.comb(50, 2)
    equity, error = sampled_equity(yours, theirs, rng)
    if calling:
        # Folding gives up the big blind you posted; calling plays for both stacks.
        ev = {"call": equity * 2 * stack_bb - stack_bb, "fold": -1.0}
        spread = 2 * stack_bb * error
        prompt = f"{VILLAIN} moves all-in for {stack_bb} bb with {described}. Call or fold?"
        assumptions = f"{VILLAIN} shoves {described}: {share:.0%} of the hands you don't block."
    else:
        # Folding gives up the small blind; a shove wins the big blind when they fold, and plays for both stacks.
        ev = {"raise": (1 - share) + share * (equity * 2 * stack_bb - stack_bb), "fold": -0.5}
        spread = share * 2 * stack_bb * error
        prompt = f"Shove {stack_bb} bb or fold? {VILLAIN} calls with {described}."
        assumptions = f"{VILLAIN} calls with {described}: {share:.0%} of the hands you don't block. Else they fold."
    worse, better = sorted(ev.values())
    if better - worse < 3 * spread + 0.05:
        return None  # too close for the sample to settle
    named = {"call": "Calling", "raise": "Shoving", "fold": "Folding"}
    found.update(
        topic="push_fold",
        question={"kind": "action", "prompt": prompt, "all_in_only": True},
        answer={
            "best": [max(ev, key=ev.get)],
            "ev_bb": {action: round(value, 2) for action, value in ev.items()},
            "equity": round(equity, 3),
            "range": text,
            "assumptions": assumptions,
            "explanation": (
                f"When called you win about {equity:.0%} against that range. "
                + " ".join(f"{named[action]}: {value:+.2f} bb." for action, value in ev.items())
            ),
        },
    )
    return found


def exact_equity(yours, theirs, board):
    """Your share of the pot against a known hand, every card to come counted: ties count half."""
    return shares([yours, theirs], board)[0][0]


def sampled_equity(yours, combos, rng=None):
    """Your equity before the flop against a range of combos, sampled, and the sample's standard error."""
    return range_share(yours, combos, rng=rng, samples=SAMPLES)


def _rank(hole, board):
    return value(hole, board)


def _drawing(hole, board):
    """Whether two cards hold nothing yet but a draw of eight outs or more on the board."""
    return made_hand(hole, board) in ("high_card", "overcards") and bool(STRONG_DRAWS & set(draws(hole, board)))


# Full tables: the preflop and hand-reading spots ---------------------------------------------------------------

# A tournament level at a table of nine: blinds of 100 and 200 and antes of 25, so a round costs 525 and M is a
# stack ÷ 525.
TOURNAMENT = {"small_blind": 100, "big_blind": 200, "ante": 25}
M_STACKS = (12, 14, 16, 18, 20, 22, 25, 28, 30)  # the value zone the chart is for [MIT 5]
# Who acts before the flop, first to last, at a table of nine and of six.
ACTING = {9: ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB"), 6: ("UTG", "HJ", "CO", "BTN", "SB", "BB")}
OPEN_SIZES = (2.25, 2.5, 2.5, 3)  # in big blinds: an open late in a tournament, or a standard one [MIT 5; JHU 3]
# Shares of hands a player opens with from each seat at a table of six, and 3-bets with: round numbers from tight to
# loose, stated with each hand-reading spot.
OPENS = {"UTG": (8, 10, 12, 15), "HJ": (12, 15, 18, 22), "CO": (18, 22, 27, 32), "BTN": (25, 32, 40, 50)}
THREE_BETS = (3, 4, 5, 7, 9, 12)


def button_for(count, position):
    """The button seat that puts seat 1 in `position` at a table of `count`, seated 1 to `count`."""
    seats = [{"seat": number} for number in range(1, count + 1)]
    names = positions(count)
    return next(
        button for button in range(1, count + 1) if names[postflop_order(seats, button).index(1)] == position
    )


def full_table(rng, count, hero_position, hero_cards, stacks, blinds, ante=0):
    """A hand at a table of `count`, with "You" in seat 1 at `hero_position` holding `hero_cards`, and everyone else
    named by their seat's position. `stacks` gives each player's chips by name (a function of the name)."""
    button = button_for(count, hero_position)
    order = postflop_order([{"seat": number} for number in range(1, count + 1)], button)
    names = [HERO if seat == 1 else position for seat, position in zip(order, positions(count), strict=True)]
    seats = [{"seat": seat, "name": name, "stack": stacks(name)} for seat, name in zip(order, names, strict=True)]
    rest = [card for card in CARDS if card not in hero_cards]
    rng.shuffle(rest)
    cards = []
    for name in names:
        cards += hero_cards if name == HERO else [rest.pop(), rest.pop()]
    small, big = blinds
    return TableHand(seats, button, small, big, "".join(cards + rest), ante=ante)


def preflop_spot(rng, facing=None):
    """A full table in a tournament with an M of 12 to 30. Folded to you in early or middle position: raise or fold?
    Or, in the lojack or hijack, a raise in front of you: play on or fold? Graded by the chart (practice.charts)."""
    facing = rng.random() < 0.4 if facing is None else facing
    acting = ACTING[9]
    if facing:
        hero_position = rng.choice(("LJ", "HJ"))
        raiser = rng.choice([seat for seat in acting[: acting.index(hero_position)] if seat in charts.SEATS])
    else:
        hero_position, raiser = rng.choice(sorted(charts.SEATS)), None
    tier = charts.tier_for(hero_position, facing)
    hand_name, tier_level = _chart_hand(rng, tier)
    m = rng.choice(M_STACKS)
    cost = TOURNAMENT["small_blind"] + TOURNAMENT["big_blind"] + 9 * TOURNAMENT["ante"]

    def stack(name):
        depth = m if name == HERO else rng.uniform(8, 40)
        return round(depth * cost / 25) * 25

    cards = rng.choice(ranges.holdings(hand_name))
    blinds = (TOURNAMENT["small_blind"], TOURNAMENT["big_blind"])
    hand = full_table(rng, 9, hero_position, cards, stack, blinds, TOURNAMENT["ante"])
    open_bb = rng.choice(OPEN_SIZES)
    while hand.actor != HERO:
        if hand.actor == raiser:
            hand.act(raiser, "raise", round(open_bb * TOURNAMENT["big_blind"]))
        else:
            hand.act(hand.actor, "fold")
    found = spot(hand, tournament=True)
    if facing:
        raised = charts.SEAT_NAMES[raiser]
        prompt = (
            f"{raised[0].upper()}{raised[1:]} raises to {open_bb:g} bb and it is folded to you {_in(hero_position)}, "
            f"with an M of {m}. What do you do?"
        )
    else:
        prompt = f"Folded to you {_in(hero_position)}, with an M of {m}. What do you do?"
    chart = charts.chart_of(tier)
    verdict = charts.answer(hand_name, tier, facing)
    found.update(
        topic="preflop_facing" if facing else "preflop_open",
        tier=tier_level,
        question={"kind": "action", "prompt": prompt},
        answer={
            **verdict,
            "chart": chart,
            "hand": hand_name,
            "explanation": _chart_explanation(hand_name, hero_position, chart, verdict, facing),
        },
    )
    return found


def _in(position):
    """ "under the gun", "in the hijack", "in UTG+1"."""
    name = charts.SEAT_NAMES[position]
    return name if position == "UTG" else f"in {name}"


def _chart_hand(rng, tier):
    """A hand for a chart spot, and how hard it is (1 to 3): one from the range, one near its edge, or any other."""
    inside = charts.hands_of(tier)
    worst = max(ranges.RANKING.index(hand) for hand in inside)
    roll = rng.random()
    if roll < 0.45:
        hand = rng.choice(sorted(inside))
        return hand, 1 if ranges.RANKING.index(hand) < worst / 2 else 2
    if roll < 0.85:
        # Hands the ranking puts near or above the range's worst hand, though the chart leaves them out: A9s, KJs.
        hand = rng.choice([hand for hand in ranges.RANKING[: worst + 20] if hand not in inside])
        return hand, 3 if ranges.RANKING.index(hand) < worst else 2
    return rng.choice([hand for hand in ranges.RANKING if hand not in inside]), 1


def _chart_explanation(hand_name, position, chart, verdict, facing):
    """Why the chart plays a hand or not, in words: the chart's figures are shown beside it."""
    hands = chart["tier_label"][0].lower() + chart["tier_label"][1:]
    if facing:
        lead = f"Facing a raise, move up a tier: from {charts.SEAT_NAMES[position]}, play early position's {hands}."
        if verdict["in_range"]:
            return f"{lead} {hand_name} is one of them: play on, by a call or a re-raise."
        return f"{lead} {hand_name} isn't one of them: fold."
    lead = f"From {charts.SEAT_NAMES[position]} the chart opens {hands}."
    if verdict["in_range"]:
        return f"{lead} {hand_name} is one of them: raise, and never limp in first [JHU 3]."
    return f"{lead} {hand_name} isn't one of them: fold."


def range_read_spot(rng):
    """At a table of six, a player raises first in while you wait in the big blind, or re-raises your open, with a
    share of hands stated with the spot. Which hands are those? The answer is that share of hands from the top of the
    ranking, by equity against a random hand (hands.ranges): ranges as percentiles [MIT 4]."""
    acting = ACTING[6]
    if rng.random() < 0.3:
        hero_position = rng.choice(("UTG", "HJ", "CO"))
        subject = rng.choice(acting[acting.index(hero_position) + 1 :])
        percent = rng.choice(THREE_BETS)
        prompt = f"You open and {charts.SEAT_NAMES[subject]} re-raises. They 3-bet {percent}% of hands. Which ones?"
        line = f"{charts.SEAT_NAMES[subject]} 3-bets"
    else:
        hero_position, subject = "BB", rng.choice(sorted(OPENS))
        percent = rng.choice(OPENS[subject])
        line = f"{charts.SEAT_NAMES[subject]} raises first in"
        prompt = f"{line[0].upper()}{line[1:]}, opening {percent}% of hands from there. Which ones?"
    # A hand you would open with, when you open; any hand when you wait in the big blind.
    dealt = sorted(ranges.top(20)) if hero_position != "BB" else ranges.RANKING
    cards = rng.choice(ranges.holdings(rng.choice(dealt)))
    stack = rng.choice((60, 100, 100, 150)) * BIG_BLIND
    hand = full_table(rng, 6, hero_position, cards, lambda name: stack, (SMALL_BLIND, BIG_BLIND))
    opened = False
    while hand.actor not in (None, HERO) or not opened:
        actor = hand.actor
        if actor == HERO:  # you open; the subject re-raises
            hand.act(HERO, "raise", round(rng.choice(OPEN_SIZES) * BIG_BLIND))
            opened = True
        elif actor == subject and (opened or hero_position == "BB"):
            to = hand.legal()["bet"] + hand.legal()["to_call"]
            hand.act(subject, "raise", round(to * 3) if opened else round(rng.choice(OPEN_SIZES) * BIG_BLIND))
            opened = True
        else:
            hand.act(actor, "fold")
    reference = ranges.top(percent)
    anchor, anchor_range = charts.nearest_anchor(percent)
    anchor_overlap = charts.overlap_score(ranges.parse(anchor_range), reference)
    found = spot(hand)
    found.update(
        topic="range_read",
        tier=1 if percent <= 10 else 2 if percent <= 25 else 3,
        question={"kind": "range", "prompt": prompt},
        answer={
            "range": ranges.notation(reference),
            "share": round(ranges.combos_of(reference) / ranges.TOTAL_COMBOS, 4),
            "percent": percent,
            "anchor": {"percent": anchor, "range": anchor_range, "overlap": round(anchor_overlap, 2)},
            "assumptions": (
                f"{line[0].upper()}{line[1:]} with {percent}% of hands: taken as the top {percent}% by equity "
                "against a random hand."
            ),
            "explanation": (
                f"The top {percent}% of hands is {ranges.notation(reference)}. The course's memory aid for the top "
                f"{anchor}%, {anchor_range}, shares {anchor_overlap:.0%} of it [MIT 4]."
            ),
        },
    )
    return found
