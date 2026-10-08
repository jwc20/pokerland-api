"""Fresh spots for one skill, played out by PokerKit so every one is a legal state (pokerland-practice-mode.md, 4.4).

Each generator deals a heads-up hand at practice.table, plays it to a decision, and writes the question with its
answer and how the answer was derived:

- `arithmetic_spot`: a bet to face, or one of yours to size up, and the numbers behind it (practice.questions).
  Exact.
- `all_in_spot`: an all-in on the flop or turn from a hand that is shown, against your draw; call or fold. Exact:
  every card to come is counted.
- `push_fold_spot`: a short stack, shove or fold in the small blind, or call or fold in the big blind, against a
  range stated with the spot [MIT 4; JHU 6]. Exact chip EV against that range; the equity is sampled, so a spot
  too close for the sample to settle is dealt again.

The players are "You" and "Villain"; the table labels them by position. Django-free, like practice.table.
"""

import math

from pokerkit import Deck
from pokerkit.analysis import parse_range

from practice.questions import arithmetic
from practice.spots import STRONG_DRAWS, pending
from practice.table import TableHand
from tracker.parsing.equity import range_share, shares, value
from tracker.parsing.facts import draws, made_hand

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


def spot(hand_table, **fields):
    """The hand up to your decision, as you see it, with the decision's context."""
    hand = {**hand_table.replay(HERO), "game": "Hold'em No Limit", "currency": "", "tournament_id": ""}
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
