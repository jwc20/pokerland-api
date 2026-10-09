"""Hold'em starting-hand ranges (FND-5 of the feature ideas): the 169 hands, their combos, range notation, and the
top X% by a ranking. pokerland-client's src/ranges.ts does the same for the range grid; the two must agree.

A hand is "AA", "AKs" or "AKo": a pair has 6 combos, a suited hand 4 and an offsuit hand 12, 1,326 in all [JHU 3,
which counts 1,225; the exact count is 1,326]. Range notation lists hands with commas: "TT+" (tens or better),
"A2s+" (suited aces), "KTo+" (KTo to KQo), "T9s-T6s", "22-55", "AK" (suited and offsuit), and "any".

RANKING orders the hands by their all-in equity against one random hand, worked out once with
tracker.parsing.equity (60,000 run-outs each, so within about 0.4% of the exact figure). It sets "the top X%": the
hands from the top until their combos make X% of the 1,326. Like tracker.parsing, this module never imports Django.
"""

import re
from itertools import combinations

from tracker.parsing.facts import hand_group

RANKS = "23456789TJQKA"
SUITS = "cdhs"
TOTAL_COMBOS = 1326
RANKING = (
    "AA KK QQ JJ TT 99 88 AKs AQs 77 AJs AKo ATs AQo KQs 66 AJo A9s ATo KJs A8s KTs A7s KQo A9o 55 KJo QJs A6s A5s "
    "K9s A8o KTo QTs A4s A7o K8s A3s QJo A2s A6o QTo K7s K9o JTs Q9s A5o 44 A4o K6s K8o Q8s A3o J9s K5s K7o Q9o JTo "
    "A2o Q7s K4s K6o T9s J8s K3s Q6s Q8o 33 J9o K2s K5o Q5s T8s J7s Q4s T9o K4o Q7o Q3s J8o K3o Q6o 98s T7s J6s 22 "
    "K2o Q5o Q2s J5s T8o J7o Q4o 97s T6s J4s Q3o T7o 87s J3s 98o J6o 96s J2s T5s Q2o J5o T4s 97o 86s J4o T6o T3s J3o "
    "95s 76s T2s 87o 85s 96o 94s J2o T5o 75s T4o 86o 93s 95o 65s 84s 76o T3o 92s 74s T2o 85o 54s 64s 83s 94o 75o "
    "82s 73s 93o 65o 84o 53s 63s 92o 74o 43s 54o 72s 64o 62s 52s 83o 42s 82o 73o 53o 63o 32s 43o 72o 52o 62o 42o 32o"
).split()
TOKEN = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so]?)(\+?)$")
SPAN = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so]?)-([2-9TJQKA])([2-9TJQKA])([so]?)$")


def rank(card_rank):
    return RANKS.index(card_rank)


def name(high, low, kind=""):
    """The hand of two ranks: "AA", "AKs", "AKo"."""
    if rank(low) > rank(high):
        high, low = low, high
    return high + low if high == low else high + low + kind


def grid():
    """The 169 hands in the grid's order, row by row from aces: a pair on the diagonal, suited hands above it,
    offsuit hands below."""
    order = RANKS[::-1]
    return [
        name(row, column, "s" if i < j else "o") if i != j else row + row
        for i, row in enumerate(order)
        for j, column in enumerate(order)
    ]


HANDS = tuple(grid())
_POSITION = {hand: i for i, hand in enumerate(RANKING)}


def combo_count(hand):
    """How many combos a hand has: 6 for a pair, 4 suited, 12 offsuit."""
    if len(hand) == 2:
        return 6
    return 4 if hand[2] == "s" else 12


def combo_of(cards):
    """Two hole cards as their hand, "AKs"; None for anything but two cards."""
    if len(cards) != 2:
        return None
    (first, first_suit), (second, second_suit) = cards[0][0] + cards[0][1], cards[1][0] + cards[1][1]
    return name(first, second, "s" if first_suit == second_suit else "o")


def _expand(hand):
    """A hand with no suitedness, "AK", as both of its hands; any other as itself."""
    if len(hand) == 2 and hand[0] != hand[1]:
        return [hand + "s", hand + "o"]
    return [hand]


def parse(notation):
    """The hands a range in notation names, as a set; ValueError on anything it can't read."""
    hands = set()
    for token in (part.strip() for part in notation.replace(";", ",").split(",")):
        if not token:
            continue
        if token.lower() in ("any", "random", "100%"):
            return set(HANDS)
        hands |= _token(token)
    return hands


def _token(token):
    if match := TOKEN.match(token):
        high, low, kind, plus = match.groups()
        if rank(low) > rank(high):
            high, low = low, high
        if high == low:
            if kind:
                raise ValueError(f"A pair has no suitedness: {token!r}")
            top = len(RANKS) if plus else rank(high) + 1
            return {r + r for r in RANKS[rank(high) : top]}
        # "A9s+": the kicker climbs to one below the top card.
        lows = RANKS[rank(low) : rank(high)] if plus else low
        return {found for kicker in lows for found in _expand(name(high, kicker, kind) if kind else high + kicker)}
    if match := SPAN.match(token):
        a, b, kind, c, d, other = match.groups()
        if kind != other:
            raise ValueError(f"Both ends of a span need the same suitedness: {token!r}")
        if a == b and c == d:  # pairs, "22-55"
            low, high = sorted((rank(a), rank(c)))
            return {r + r for r in RANKS[low : high + 1]}
        if a == c:  # one top card, kickers between: "T9s-T6s"
            low, high = sorted((rank(b), rank(d)))
            return {
                found
                for kicker in RANKS[low : high + 1]
                if kicker != a
                for found in _expand(name(a, kicker, kind) if kind else a + kicker)
            }
    raise ValueError(f"Not a range: {token!r}")


def top(percent):
    """The hands from the top of RANKING until their combos make `percent`% of all 1,326: a hand counts once the
    hands before it make less than that share."""
    hands = set()
    total = 0
    for hand in RANKING:
        if total >= percent / 100 * TOTAL_COMBOS:
            break
        hands.add(hand)
        total += combo_count(hand)
    return hands


def percentile(hand):
    """Where a hand sits in RANKING by combos, from 0 (the best) to 1 (the worst)."""
    before = sum(combo_count(other) for other in RANKING[: _POSITION[hand]])
    return round(before / (TOTAL_COMBOS - combo_count(hand)), 4)


def group_of(hand):
    """The JHU class of one of the 169 starting hands (tracker.parsing.facts.hand_group): "premium", "junk", ..."""
    suit = "s" if hand.endswith("s") else "c"
    return hand_group([hand[0] + "s", hand[1] + (suit if hand[0] != hand[1] else "h")])


def holdings(hand, dead=()):
    """A hand's combos as pairs of cards, leaving out any with a card in `dead`."""
    high, low = hand[0], hand[1]
    if high == low:
        pairs = combinations([high + suit for suit in SUITS], 2)
    elif hand[2] == "s":
        pairs = ((high + suit, low + suit) for suit in SUITS)
    else:
        pairs = ((high + one, low + two) for one in SUITS for two in SUITS if one != two)
    return [list(pair) for pair in pairs if pair[0] not in dead and pair[1] not in dead]
