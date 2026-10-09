"""Reading the cards in a replay (A2 and A3 of the feature ideas), and the equity calculator behind them.

- `outs`: at each of the hero's decisions on the flop and turn, their equity against the live opponents whose cards
  were later shown, and what every card to come does: an out wins, a split out ties, and a dirty out would beat the
  hand the opponent had but improves it more, so it still loses; when the hero is ahead, a danger card puts them
  behind, and a counterfeit does it by pairing the board [JHU 2]. With the rule of 2 and 4 beside it, and its
  correction above eight outs [MIT 3; JHU 7].
- `board_reader`: on each street, the nuts and the next best hands possible, what the board allows, and where the
  hero's hand ranks among every holding left [JHU 1]: "you beat 99% of the holdings left; the 6 that beat you are
  three nines and three tens".
- `equity`: a hand's equity against a known hand, a range, or a kind of hand on the board, exact when the run-outs
  are few enough to count and sampled otherwise.

Django-free, like tracker.parsing: a hand is a dict shaped like a stored hand's replay, with its hero and game.
"""

import random
from collections import Counter, defaultdict
from itertools import combinations

from hands import ranges
from tracker.parsing.equity import CARDS, pot_shares, range_share, shares, value
from tracker.parsing.facts import STRONG, board_texture, draws, made_hand

MOVES = ("fold", "check", "call", "bet", "raise")
CATEGORIES = (
    "high_card",
    "pair",
    "two_pair",
    "three_of_a_kind",
    "straight",
    "flush",
    "full_house",
    "four_of_a_kind",
    "straight_flush",
)
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
NAMES = {
    1: "five",  # an ace playing low only ever tops a wheel, which `_ranks` reads as five-high
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "jack",
    12: "queen",
    13: "king",
    14: "ace",
}
OMAHA_SAMPLES = 400  # Omaha holdings drawn to rank the hero's hand, too many to count: within about 5% either way
TOOL_SAMPLES = 4000  # run-outs drawn when the equity calculator can't count them all
EXACT_LIMIT = 60_000  # the most hand evaluations the calculator counts exactly
# Kinds of hand on the board an opponent can be put on when their cards weren't shown (A2).
HAND_KINDS = ("any", "overpair", "top_pair", "two_pair_plus", "set", "flush_draw", "straight_draw")
_DECENT = {"overpair", "top_pair", "top_pair_top_kicker"}  # strong, but short of two pair


def _ranks(packed):
    """A value's category and its five ranks, most telling first (tracker.parsing.equity._pack)."""
    return packed >> 20, [(packed >> (16 - 4 * i)) & 15 for i in range(5)]


def plural(rank):
    return "sixes" if rank == 6 else f"{NAMES[rank]}s"


def article(word):
    return f"an {word}" if word[0] in "aeiou" else f"a {word}"


def describe(packed):
    """A value in words: "a pair of kings", "nines full of kings", "an ace-high flush"."""
    category, (first, second, *_) = _ranks(packed)
    if category == HIGH_CARD:
        return f"{NAMES[first]} high"
    if category == PAIR:
        return f"a pair of {plural(first)}"
    if category == TWO_PAIR:
        return f"two pair, {plural(first)} and {plural(second)}"
    if category == TRIPS:
        return f"three {plural(first)}"
    if category == STRAIGHT:
        return article(f"{NAMES[first]}-high straight")
    if category == FLUSH:
        return article(f"{NAMES[first]}-high flush")
    if category == FULL_HOUSE:
        return f"{plural(first)} full of {plural(second)}"
    if category == QUADS:
        return f"four {plural(first)}"
    return "a royal flush" if first == 14 else article(f"{NAMES[first]}-high straight flush")


def group_name(packed):
    """The kind of holding a value is, for counting those that beat the hero: "three nines", "flushes, ace-high"."""
    category, (first, *_) = _ranks(packed)
    return {
        HIGH_CARD: f"{NAMES[first]}-high hands",
        PAIR: f"pairs of {plural(first)}",
        TWO_PAIR: f"two pair, {plural(first)} up",
        TRIPS: f"three {plural(first)}",
        STRAIGHT: f"{NAMES[first]}-high straights",
        FLUSH: f"{NAMES[first]}-high flushes",
        FULL_HOUSE: f"{plural(first)} full",
        QUADS: f"four {plural(first)}",
        STRAIGHT_FLUSH: "royal flushes" if first == 14 else f"{NAMES[first]}-high straight flushes",
    }[category]


def outs(hand):
    """The hero's outs at each of their decisions on the flop and the turn, against the live opponents whose cards
    were shown. Each has the decision's event index in the hand's events, its street and board, those opponents and
    how many others were live with unknown cards; and, with any opponent known, the hero's equity (every card to
    come counted), their share after the next card alone, where they stood, the cards that matter and the rule of
    thumb's estimate."""
    hero = hand.get("hero")
    cards = {player["name"]: player["cards"] for player in hand["players"]}
    mine = cards.get(hero) or []
    omaha = "Omaha" in hand.get("game", "")
    if len(mine) != (4 if omaha else 2):
        return []
    folded = set()
    board = []
    found = []
    for i, event in enumerate(hand["events"]):
        kind = event["type"]
        if kind == "street" and "board" in event:
            board = event["board"]
        if kind in MOVES and event.get("player") == hero and event["street"] in ("flop", "turn"):
            live = [name for name in cards if name != hero and name not in folded]
            known = [(name, cards[name]) for name in live if len(cards[name]) == len(mine)]
            found.append(_decision(i, event["street"], list(board), mine, known, len(live) - len(known), omaha))
        if kind == "fold":
            folded.add(event["player"])
    return found


def _decision(index, street, board, mine, villains, unknown, omaha):
    entry = {
        "event": index,
        "street": street,
        "board": board,
        "villains": [{"name": name, "cards": held} for name, held in villains],
        "unknown": unknown,
        "cards_to_come": 5 - len(board),
    }
    if not villains:
        return {**entry, "equity": None, "next_card": None, "standing": None, "outs": [], "counts": {}, "rule": None}
    theirs = [held for _, held in villains]
    rng = random.Random(f"{index}:{''.join(board)}")
    (equity, *_), exact = pot_shares([mine, *theirs], board, [(1.0, range(1 + len(theirs)))], omaha=omaha, rng=rng)
    known = {*board, *mine, *(card for held in theirs for card in held)}
    mine_now = value(mine, board, omaha)
    best_now = max(value(held, board, omaha) for held in theirs)
    board_ranks = {card[0] for card in board}
    counts = Counter()
    listed = []
    after_next = 0.0
    left = [card for card in CARDS if card not in known]
    for card in left:
        after = [*board, card]
        mine_after = value(mine, after, omaha)
        best_after = max(value(held, after, omaha) for held in theirs)
        after_next += 1.0 if mine_after > best_after else 0.5 if mine_after == best_after else 0.0
        kind = _card_kind(mine_now, best_now, mine_after, best_after, card[0] in board_ranks)
        if kind:
            counts[kind] += 1
            listed.append({"card": card, "kind": kind})
    clean = counts["out"]
    # The rule of 2 and 4 [MIT 3], corrected above eight outs with two cards to come [JHU 7].
    rule = 2 * clean if entry["cards_to_come"] == 1 else 4 * clean - max(0, clean - 8)
    standing = "ahead" if mine_now > best_now else "tied" if mine_now == best_now else "behind"
    return {
        **entry,
        "equity": round(equity, 4),
        "exact": exact,
        "next_card": round(after_next / len(left), 4),
        "standing": standing,
        "outs": listed,
        "counts": dict(counts),
        "rule": min(rule, 100),
    }


def _card_kind(mine_now, best_now, mine_after, best_after, pairs_board):
    """What a card to come does for a hero who was behind (out, split, dirty) or not (danger, counterfeit)."""
    if mine_now < best_now:
        if mine_after > best_after:
            return "out"
        if mine_after == best_after:
            return "split"
        if mine_after > best_now:
            return "dirty"  # it would beat the hand they had, but it improves theirs more
        return None
    if mine_after < best_after:
        # The board pairing and the hero's hand going nowhere: their hand is counterfeited.
        return "counterfeit" if pairs_board and mine_after >> 20 == mine_now >> 20 else "danger"
    return None


def board_reader(hand):
    """Each street's board read: what it allows, the nuts and the next best hands, and the hero's hand among every
    holding left, with warnings about it."""
    board = hand["board"]
    omaha = "Omaha" in hand.get("game", "")
    mine = next((player["cards"] for player in hand["players"] if player["name"] == hand.get("hero")), [])
    if len(mine) != (4 if omaha else 2):
        mine = []
    return [
        read_board(street, board[:count], mine, omaha)
        for street, count in (("flop", 3), ("turn", 4), ("river", 5))
        if len(board) >= count
    ]


def read_board(street, board, mine, omaha=False):
    """One street's board: its texture, the best hands possible with how many two-card combos make each (in Omaha,
    two hole cards played with three of the board), and the hero's hand, if known."""
    texture = board_texture(board)
    left = [card for card in CARDS if card not in board]
    values = {pair: value(pair, board, omaha) for pair in combinations(left, 2)}
    best = {}
    combos = Counter()
    for pair, packed in values.items():
        category = packed >> 20
        combos[category] += 1
        if packed > best.get(category, (0, None))[0]:
            best[category] = (packed, pair)
    classes = [
        {
            "category": CATEGORIES[category],
            "description": describe(packed),
            "cards": list(pair),
            "combos": combos[category],
        }
        for category, (packed, pair) in sorted(best.items(), key=lambda item: -item[1][0])[:3]
    ]
    return {
        "street": street,
        "board": list(board),
        "texture": {
            "flush_possible": texture["suited"] >= 3,
            "straight_possible": texture["straight_possible"],
            "full_house_possible": texture["paired"],
            "wetness": texture["wetness"],
        },
        "nuts": classes[0],
        "classes": classes,
        "hero": (_omaha_rank(mine, board) if omaha else _rank(mine, board, values)) if mine else None,
    }


def _rank(mine, board, values):
    """The hero's hold'em hand against every two cards left: how many beat it, tie it and lose to it, what beats it,
    and the warnings worth giving."""
    held = value(mine, board)
    better = defaultdict(int)
    counts = Counter()
    for pair, packed in values.items():
        if pair[0] in mine or pair[1] in mine:
            continue
        if packed > held:
            counts["better"] += 1
            better[group_name(packed), packed >> 16] += 1
        else:
            counts["equal" if packed == held else "worse"] += 1
    total = sum(counts.values())
    beaten_by = [
        {"description": name, "combos": count}
        for (name, _), count in sorted(better.items(), key=lambda item: -item[0][1])[:5]
    ]
    return {
        "description": describe(held),
        "category": CATEGORIES[held >> 20],
        "better": counts["better"],
        "equal": counts["equal"],
        "worse": counts["worse"],
        "beats": round((counts["worse"] + counts["equal"] / 2) / total, 4) if total else None,
        "beaten_by": beaten_by,
        "sampled": False,
        "warnings": _warnings(mine, board, held, values),
    }


def _warnings(mine, board, held, values):
    """What a hold'em hand should know about itself: a flush that isn't the nut flush, the low end of a straight,
    or two pair a board pair can counterfeit [JHU 1]."""
    category = held >> 20
    warnings = []
    beaten_in_kind = any(packed >> 20 == category and packed > held for packed in values.values())
    if category == FLUSH and beaten_in_kind:
        warnings.append("not_the_nut_flush")
    if category == STRAIGHT and beaten_in_kind:
        warnings.append("low_straight")
    if len(board) < 5 and made_hand(mine, board) == "two_pair":
        lower = min(ranges.rank(card[0]) for card in mine)
        mine_ranks = {card[0] for card in mine}
        if any(ranges.rank(card[0]) > lower and card[0] not in mine_ranks for card in board):
            warnings.append("counterfeit_risk")
    return warnings


def _omaha_rank(mine, board):
    """The hero's Omaha hand against sampled four-card holdings: too many to count them all."""
    held = value(mine, board, omaha=True)
    left = [card for card in CARDS if card not in board and card not in mine]
    rng = random.Random("".join(mine + board))
    counts = Counter()
    for _ in range(OMAHA_SAMPLES):
        packed = value(rng.sample(left, 4), board, omaha=True)
        counts["better" if packed > held else "equal" if packed == held else "worse"] += 1
    return {
        "description": describe(held),
        "category": CATEGORIES[held >> 20],
        **{key: counts[key] for key in ("better", "equal", "worse")},
        "beats": round((counts["worse"] + counts["equal"] / 2) / OMAHA_SAMPLES, 4),
        "beaten_by": [],
        "sampled": True,
        "warnings": [],
    }


def kind_holdings(kind, board, dead=()):
    """Every two-card holding left that makes a kind of hand on the board (HAND_KINDS)."""
    left = [card for card in CARDS if card not in board and card not in dead]
    found = []
    for pair in combinations(left, 2):
        if kind == "any" or _is_kind(kind, list(pair), board):
            found.append(list(pair))
    return found


def _is_kind(kind, pair, board):
    made = made_hand(pair, board)
    if kind == "overpair":
        return made == "overpair"
    if kind == "top_pair":
        return made in ("top_pair", "top_pair_top_kicker")
    if kind == "two_pair_plus":
        return made in STRONG and made not in _DECENT
    if kind == "set":
        return made == "set"
    drawing = draws(pair, board) if len(board) < 5 else []
    if kind == "flush_draw":
        return "flush_draw" in drawing or "nut_flush_draw" in drawing
    return "open_ended" in drawing or "double_gutshot" in drawing


def equity(mine, board, villain, dead=()):
    """`mine`'s share of the pot against `villain` as the board runs out: {"cards"}, {"range": notation} or
    {"kind": one of HAND_KINDS}. Returns {equity, stderr, exact, combos}; combos holding a known card are left out.
    ValueError if nothing is left for the villain to hold."""
    known = {*mine, *board, *dead}
    if "cards" in villain:
        holdings = [villain["cards"]]
    elif "range" in villain:
        holdings = [
            pair for hand in sorted(ranges.parse(villain["range"])) for pair in ranges.holdings(hand, dead=known)
        ]
    else:
        holdings = kind_holdings(villain["kind"], board, dead=known)
    holdings = [pair for pair in holdings if not known & set(pair)]
    if not holdings:
        raise ValueError("No holding is left for the opponent.")
    missing = 5 - len(board)
    run_outs = 1
    for i in range(missing):
        run_outs = run_outs * (52 - len(known) - 2 - i) // (i + 1)
    if len(holdings) * run_outs <= EXACT_LIMIT:
        total = sum(shares([mine, pair], board, dead=dead)[0][0] for pair in holdings)
        return {"equity": round(total / len(holdings), 4), "stderr": 0.0, "exact": True, "combos": len(holdings)}
    rng = random.Random(f"{''.join(mine)}:{''.join(board)}:{len(holdings)}")
    share, stderr = range_share(mine, holdings, board, rng=rng, samples=TOOL_SAMPLES)
    return {"equity": round(share, 4), "stderr": round(stderr, 4), "exact": False, "combos": len(holdings)}
