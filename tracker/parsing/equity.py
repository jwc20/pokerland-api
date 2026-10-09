"""Equity: each player's share of the pot as the board runs out, and what they could expect when the money went in
(FND-2 of the feature ideas).

- `value` ranks a hold'em hand of five to seven cards, or an Omaha hand (two hole cards and three of the board), as
  an integer: the better hand has the bigger one. It is a plain-integer evaluator, about ten times quicker than
  PokerKit's in CPython, and the tests check it against PokerKit.
- `shares` gives each of several known hands its share of a pot, ties split: exact, every card to come counted,
  when two cards or fewer are to come (one in Omaha, whose hands cost sixty times as much to rank); else from
  sampled run-outs. `range_share` plays a hand against a range.
- `all_in` works out, for a hand where the money went in before the river with every live hand known, each live
  player's equity and the chips they could expect, side pot by side pot.

Sampling is seeded by the caller, so a hand parsed twice gets the same numbers. Like the rest of tracker.parsing,
it never imports Django.
"""

import math
import random
from collections import defaultdict
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARDS = [rank + suit for rank in RANKS for suit in SUITS]
# A card as (rank 2-14, suit 0-3).
PARSED = {card: (RANKS.index(card[0]) + 2, SUITS.index(card[1])) for card in CARDS}
# Run-outs drawn when there are too many to count: an equity within about 2% for two hold'em hands, 95% of the
# time, and within about 6% in Omaha.
SAMPLES = 2000
OMAHA_SAMPLES = 300
MOVES = ("fold", "check", "call", "bet", "raise")

# Hand categories, the first part of a value.
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)


def _pack(category, ranks):
    """A category and up to five ranks, most telling first, as one comparable integer."""
    packed = category
    for i in range(5):
        packed = packed * 16 + (ranks[i] if i < len(ranks) else 0)
    return packed


def _straight(ranks):
    """The top rank of the best straight among `ranks` (a set), 5 for a wheel; 0 for none."""
    if 14 in ranks:
        ranks = ranks | {1}
    for top in range(14, 4, -1):
        if all(rank in ranks for rank in range(top - 4, top + 1)):
            return top
    return 0


def _best(cards):
    """The value of the best five of five to seven parsed cards."""
    counts = defaultdict(int)
    by_suit = defaultdict(list)
    for rank, suit in cards:
        counts[rank] += 1
        by_suit[suit].append(rank)
    flush = next((ranks for ranks in by_suit.values() if len(ranks) >= 5), None)
    if flush:
        top = _straight(set(flush))
        if top:
            return _pack(STRAIGHT_FLUSH, [top])
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)  # by count, then rank
    (count, rank), rest = groups[0], groups[1:]
    if count == 4:
        return _pack(QUADS, [rank, max(other for _, other in rest)])
    if count == 3 and rest and rest[0][0] >= 2:
        return _pack(FULL_HOUSE, [rank, rest[0][1]])
    if flush:
        return _pack(FLUSH, sorted(flush, reverse=True)[:5])
    top = _straight(set(counts))
    if top:
        return _pack(STRAIGHT, [top])
    singles = sorted((other for count_, other in rest if count_ == 1), reverse=True)
    if count == 3:
        return _pack(TRIPS, [rank, *singles[:2]])
    if count == 2 and rest and rest[0][0] == 2:
        low = rest[0][1]
        kicker = max(other for _, other in rest[1:]) if rest[1:] else 0
        return _pack(TWO_PAIR, [rank, low, kicker])
    if count == 2:
        return _pack(PAIR, [rank, *singles[:3]])
    return _pack(HIGH_CARD, sorted(counts, reverse=True)[:5])


def value(hole, board, omaha=False):
    """The value of a hand: hold'em's best five of hole and board, or Omaha's best of two hole cards and three of
    the board. Cards are strings such as "Ah"."""
    hole = [PARSED[card] for card in hole]
    board = [PARSED[card] for card in board]
    if not omaha:
        return _best(hole + board)
    return max(_best([*two, *three]) for two in combinations(hole, 2) for three in combinations(board, 3))


def is_nuts(hole, board):
    """Whether no two cards left in the deck make a better hold'em hand than `hole` on `board`: ties allowed."""
    parsed = [PARSED[card] for card in board]
    mine = _best([PARSED[card] for card in hole] + parsed)
    left = [PARSED[card] for card in CARDS if card not in hole and card not in board]
    return not any(_best([one, two, *parsed]) > mine for one, two in combinations(left, 2))


def run_outs(board, known, rng, *, omaha=False, samples=None):
    """Complete boards from `board`: every one when two cards or fewer are to come (one in Omaha), else `samples`
    drawn with `rng` from the cards left. Returns (boards, whether they are every one)."""
    missing = 5 - len(board)
    left = [card for card in CARDS if card not in known]
    if missing <= (1 if omaha else 2):
        return ([[*board, *run] for run in combinations(left, missing)], True)
    count = samples or (OMAHA_SAMPLES if omaha else SAMPLES)
    return ([[*board, *rng.sample(left, missing)] for _ in range(count)], False)


def pot_shares(holes, board, pots, *, omaha=False, dead=(), rng=None, samples=None):
    """The chips each of `holes` can expect from `pots`, as the board runs out: (expected chips per hand, exact).

    `pots` are (amount, the indexes of the hands that can win it), main pot first. A pot tied is split.
    `dead` are other known cards, which can't come. `samples` overrides how many run-outs are drawn.
    """
    known = {*board, *dead, *(card for hole in holes for card in hole)}
    boards, exact = run_outs(list(board), known, rng or random.Random(), omaha=omaha, samples=samples)
    expected = [0.0] * len(holes)
    for full in boards:
        values = [value(hole, full, omaha) for hole in holes]
        for amount, eligible in pots:
            best = max(values[i] for i in eligible)
            winners = [i for i in eligible if values[i] == best]
            for i in winners:
                expected[i] += amount / len(winners)
    return [chips / len(boards) for chips in expected], exact


def shares(holes, board=(), **options):
    """Each hand's share of one pot, ties split, as the board runs out: (shares, exact). Options as `pot_shares`."""
    return pot_shares(holes, board, [(1.0, range(len(holes)))], **options)


def range_share(hole, combos, board=(), *, rng=None, samples=SAMPLES):
    """A hand's share of the pot against a hand drawn from `combos`, which mustn't hold its cards, as the board
    runs out: (share, its standard error). Sampled: a combo and a board each time."""
    rng = rng or random.Random()
    combos = [[card if isinstance(card, str) else repr(card) for card in combo] for combo in combos]
    total = 0.0
    for _ in range(samples):
        theirs = rng.choice(combos)
        known = {*hole, *board, *theirs}
        full = [*board, *rng.sample([card for card in CARDS if card not in known], 5 - len(board))]
        mine, other = value(hole, full), value(theirs, full)
        total += 1.0 if mine > other else 0.5 if mine == other else 0.0
    share = total / samples
    return share, math.sqrt(max(share * (1 - share), 0.01) / samples)


def side_pots(put_in, live):
    """The pots the chips make, main pot first: (amount, the live players who can win it).

    `put_in` is every player's chips in the pot, folded players' included; `live` are those still in. A pot's
    players are those who put in at least its level.
    """
    levels = sorted({put_in[name] for name in live if put_in[name] > 0})
    pots = []
    floor = 0
    for level in levels:
        amount = sum(min(paid, level) - min(paid, floor) for paid in put_in.values())
        if amount:
            pots.append((amount, [name for name in live if put_in[name] >= level]))
        floor = level
    beyond = sum(max(0, paid - floor) for paid in put_in.values())  # dead money above every live player's
    if beyond and pots:
        pots[-1] = (pots[-1][0] + beyond, pots[-1][1])
    return pots


def all_in(hand, samples=None):
    """Each live player's equity and expected chips when the money went in before the river, every live hand known.

    `hand` is a hand as tracker.parsing.pokerstars.extract makes it (players with their cards, events, board,
    game, site and hand number), or a practice hand shaped like one. The money is in when the last decision has been
    made: what the board was then is what each player could see. Returns {name: {"equity", "expected",
    "invested"}}: their expected chips over their pots, those chips, and what they put in, before any rake; or
    None when the money went in on the river, a live hand is unknown, or no live player was all-in.
    """
    put_in = defaultdict(int)
    folded = set()
    all_in_players = set()
    board = []
    settled = None
    for event in hand["events"]:
        kind = event["type"]
        if kind == "street" and "board" in event:
            board = event["board"]
        if kind in ("post", "call", "bet", "raise"):
            put_in[event["player"]] += event.get("amount", 0)
            if event.get("all_in"):
                all_in_players.add(event["player"])
        elif kind == "return":
            put_in[event["player"]] -= event["amount"]
        if kind == "fold":
            folded.add(event["player"])
        if kind in MOVES:
            settled = list(board)
    if settled is None or len(settled) >= 5:
        return None
    cards = {player["name"]: player["cards"] for player in hand["players"]}
    live = [name for name in cards if name not in folded and name in put_in]
    if len(live) < 2 or not all_in_players & set(live) or any(len(cards[name]) < 2 for name in live):
        return None
    pots = side_pots(put_in, live)
    dead = [card for name, held in cards.items() if name not in live for card in held]
    rng = random.Random(f"{hand.get('site', '')}:{hand.get('hand_id', '')}")
    expected, _ = pot_shares(
        [cards[name] for name in live],
        settled,
        [(amount, [live.index(name) for name in eligible]) for amount, eligible in pots],
        omaha="Omaha" in hand.get("game", ""),
        dead=dead,
        rng=rng,
        samples=samples,
    )
    contested = {name: sum(amount for amount, eligible in pots if name in eligible) for name in live}
    return {
        name: {
            "equity": chips / contested[name] if contested[name] else 0.0,
            "expected": chips,
            "invested": put_in[name],
        }
        for name, chips in zip(live, expected, strict=True)
    }
