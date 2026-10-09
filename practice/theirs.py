"""Their seat (pokerland-practice-mode.md, 3.4 and 4.2): an opponent's decisions in one of your hands, when their cards
were shown, played from their chair. "Bob called your raise with 9-7 suited; would you have?" The hand belongs to the
user who played it, so no consent question arises, and the names stay.

Two kinds of spot come from such a hand:

- **Their move** (`their_action`): the table from their seat, their cards face up and yours hidden, at one of their
  decisions. What do you do? Graded by the house playbook where a rule settles it, else a reflection; then what
  they did, and how the hand went for them.
- **Their range** (`their_range`, hand reading): the table from your own seat just after their first move before the
  flop, their cards still hidden. Which hands does that line represent? The stated range is a share of hands at the
  top of the ranking, the share their own rate for that move in your hands (FND-6), drawn towards a typical
  player's while the sample is small. Graded by overlap, partial credit; then their cards are shown.

The stated range is a model, and says so: a player who 3-bets 6% of the time is taken to 3-bet the best 6% of hands,
and one who calls a raise to call the hands just below those. Real ranges are lumpier, so the spot names its
assumptions, as every stated range does (the main doc's section 5).
"""

import random

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from hands import ranges
from hands.models import HandPlayer, Opponent
from practice.models import Scenario
from practice.rules import evaluate
from practice.sets import (
    DAILY_SIZE,
    MIN_AGE,
    clear,
    hand_data,
    house_playbook,
    legal_of,
    numbers_of,
    quoted_card,
    save_set,
    table_spec,
)
from practice.spots import POSTFLOP, decisions

RECENT_SHOWDOWNS = 200  # opponents' shown hands looked at, the latest first
PRIOR = 10  # chances' worth of a typical player's rate a player's own rate is drawn towards
# A typical player's rates, in percent, when the user's own opponents give too little to go on: a tight-aggressive
# regular's, as the synthetic hands play them (dev-tools/gen_hands.py).
TYPICAL = {"rfi": 18.0, "three_bet": 6.0, "cold_call": 10.0, "limp": 6.0}
TYPICAL_RFI = {"UTG": 12.0, "UTG+1": 13.0, "UTG+2": 14.0, "LJ": 16.0, "HJ": 18.0, "CO": 26.0, "BTN": 40.0, "SB": 32.0}
POPULATION_MIN = 200  # chances the user's opponents together need before their rate stands for a typical player's
# The lines before the flop a range is asked of: what the player did, in words, and the rates that bound the range.
LINES = {
    "rfi": "raises first in",
    "three_bet": "3-bets",
    "cold_call": "calls a raise",
    "limp": "limps in",
}
SEATS = {
    "UTG": "under the gun",
    "UTG+1": "from UTG+1",
    "UTG+2": "from UTG+2",
    "LJ": "from the lojack",
    "HJ": "from the hijack",
    "CO": "from the cutoff",
    "BTN": "on the button",
    "SB": "from the small blind",
    "BB": "from the big blind",
}


def showdowns(user, now=None):
    """The user's hands, at least a day old, in which an opponent's cards were shown: (hand, their HandPlayer row),
    the latest first."""
    now = now or timezone.now()
    rows = (
        HandPlayer.objects.filter(user=user, is_hero=False, hand__played_at__lt=now - MIN_AGE)
        .exclude(cards=[])
        .exclude(hand__hero="")  # hands the user sat out (hands.filters.PLAYED)
        .select_related("hand")
        .order_by("-hand__played_at")[:RECENT_SHOWDOWNS]
    )
    return [(row.hand, row) for row in rows if len(row.cards) == 2]  # hold'em: the ranges are hold'em's


def their_moves(hand, data, name):
    """An opponent's decisions in a hand, as practice.spots reads them from their seat."""
    return decisions({**data, "hero": name}, name)


def interest(context):
    """How much one of their decisions is worth playing from their seat; 0 for one that teaches nothing."""
    move = context["move"]["action"]
    if context["street"] == "preflop" and move == "fold":
        return 0
    score = 1.0
    if move in ("call", "bet", "raise"):
        score += 1
    if context["street"] in POSTFLOP:
        score += 1
    if context["pot_bb"] >= 15:
        score += 1
    return score


def action_scenario(user, hand, data, name, context, rules):
    """A spot from an opponent's decision, at their seat: what do you do here?"""
    advice = clear(evaluate(context, rules))
    rule = next((card for card in rules if advice and card["id"] == advice["rule"]), None)
    theirs = {**data, "hero": name}
    spec = {
        **table_spec(theirs, context["step"], "names"),
        "question": {"kind": "action", "prompt": f"You're in {name}'s seat. What do you do?"},
        "legal": legal_of(context),
        "panel": True,
    }
    net = next(player["net"] for player in data["players"] if player["name"] == name)
    answer = {
        "advice": advice,
        "rule": quoted_card(rule),
        "context": numbers_of(context),
        "player": name,
        "they_did": context["move"],
        "result": {"hand": hand.pk, "step": context["step"], "net_bb": round(net / hand.big_blind, 2)},
    }
    scenario, _ = Scenario.objects.get_or_create(
        owner=user,
        hand=hand,
        step=context["step"],
        topic="their_action",
        defaults={
            "source": "their_seat",
            "spec": spec,
            "answer": answer,
            "grading": "rule" if advice else "reflection",
            "skills": ["preflop" if context["street"] == "preflop" else "postflop"],
            "tier": 2 if advice else 1,
        },
    )
    return scenario


def line_of(row):
    """The line before the flop a range is asked of, from their HandPlayer row; None for any other."""
    for line in ("rfi", "three_bet", "cold_call", "limp"):
        if getattr(row, f"{line}_did"):
            return line
    return None


def typical(user):
    """A typical player's rates in the user's games: their opponents' together, once there are chances enough;
    else TYPICAL."""
    totals = Opponent.objects.filter(user=user).values_list("counters", flat=True)
    rates = dict(TYPICAL)
    for line in TYPICAL:
        did = sum(counters.get(f"{line}_did", 0) for counters in totals)
        could = sum(counters.get(f"{line}_could", 0) for counters in totals)
        if could >= POPULATION_MIN:
            rates[line] = 100 * did / could
    return rates


def drawn(did, could, towards, prior=PRIOR):
    """A rate in percent from `did` of `could`, drawn towards `towards` by `prior` chances' worth of it."""
    return 100 * (did + prior * towards / 100) / (could + prior)


def rate(user, hand, row, line, typical_rates):
    """Their rate for a line, in percent, with what it rests on: their raises first in from that seat, or their rate
    for the line anywhere, each drawn towards a typical player's."""
    opponent = Opponent.objects.filter(user=user, site=hand.site, name=row.name).first()
    counters = opponent.counters if opponent else {}
    did, could = counters.get(f"{line}_did", 0), counters.get(f"{line}_could", 0)
    overall = drawn(did, could, typical_rates[line])
    basis = {"line": line, "did": did, "could": could, "typical": round(typical_rates[line], 1), "seat": ""}
    if line == "rfi" and row.position in TYPICAL_RFI:
        seat = HandPlayer.objects.filter(
            user=user, is_hero=False, hand__site=hand.site, name=row.name, position=row.position
        ).aggregate(did=Sum("rfi_did", default=0), could=Sum("rfi_could", default=0))
        # From this seat: towards their own rate anywhere, scaled by how much wider a typical player opens here.
        scaled = overall * TYPICAL_RFI[row.position] / TYPICAL["rfi"]
        basis.update(did=seat["did"], could=seat["could"], seat=row.position, typical=round(scaled, 1))
        return drawn(seat["did"], seat["could"], scaled), basis
    return overall, basis


# A call's or a limp's band starts below the raises it didn't make: a cold call below the 3-bets, a limp below the
# raises first in.
BELOW = {"cold_call": "three_bet", "limp": "rfi"}
BELOW_VERBS = {"cold_call": "3-bet", "limp": "raise first in"}


def stated_range(line, share, above=0.0):
    """The hands a line represents under the linear model: the top `share`% for a raise; for a call or a limp, the
    band of `share`% just below the top `above`%, the raises it didn't make."""
    return ranges.top(above + share) - ranges.top(above) if line in BELOW else ranges.top(share)


def range_scenario(user, hand, data, row, context, typical_rates):
    """A spot from an opponent's first move before the flop: which hands does it represent?"""
    line = line_of(row)
    if line is None:
        return None
    main, basis = rate(user, hand, row, line, typical_rates)
    above = rate(user, hand, row, BELOW[line], typical_rates)[0] if line in BELOW else 0.0
    reference = stated_range(line, main, above)
    if not reference:
        return None
    name, seat = row.name, SEATS.get(row.position, "")
    combo = ranges.combo_of(row.cards)
    where = f" {SEATS[basis['seat']]}" if basis["seat"] else ""
    sample = f"{basis['did']} of their {basis['could']} chances{where} in your hands"
    few = " while that is few" if basis["could"] < 3 * PRIOR else ""
    if basis["seat"]:
        towards = f"{basis['typical']:.0f}%, what their raises first in elsewhere suggest for the seat"
    else:
        towards = f"a typical player's {basis['typical']:.0f}%"
    share = round(ranges.combos_of(reference) / ranges.TOTAL_COMBOS, 4)
    if line in BELOW:
        taken = f"the {main:.0f}% of hands just below the {above:.0f}% they {BELOW_VERBS[line]} with"
    else:
        taken = f"the top {main:.0f}% of hands"
    spec = {
        **table_spec(data, context["step"] + 1, "names"),
        "question": {"kind": "range", "prompt": f"{name} {LINES[line]} {seat}. Which hands does that represent?"},
        "panel": False,
    }
    answer = {
        "range": ranges.notation(reference),
        "share": share,
        "percent": round(main),
        "player": name,
        "their_cards": row.cards,
        "their_hand": combo,
        "in_stated": combo in reference,
        "assumptions": (
            f"{name} {LINES[line]} {main:.0f}% of the time they can: {sample}, drawn towards {towards}{few}. Their "
            f"range is taken as {taken}, by equity against a random hand."
        ),
        "explanation": f"{name} showed {' '.join(row.cards)}, {combo}: "
        + ("inside the stated range." if combo in reference else "outside the stated range: a surprise."),
    }
    scenario, _ = Scenario.objects.get_or_create(
        owner=user,
        hand=hand,
        step=context["step"],
        topic="their_range",
        defaults={
            "source": "their_seat",
            "spec": spec,
            "answer": answer,
            "grading": "reference",
            "skills": ["hand_reading"],
            "tier": 2,
        },
    )
    return scenario


def spots(user, rng, actions=5, reads=3):
    """Spots from opponents' seats in the user's hands: their moves and their ranges, the most worth studying first."""
    rules = house_playbook().rules
    typical_rates = typical(user)
    taken = set(Scenario.objects.filter(owner=user, source="their_seat").values_list("hand_id", "step", "topic"))
    moves, reads_found = [], []
    for hand, row in showdowns(user):
        data = hand_data(hand)
        contexts = their_moves(hand, data, row.name)
        for context in contexts:
            if (hand.pk, context["step"], "their_action") not in taken and (score := interest(context)):
                moves.append((score + rng.random(), hand, data, row, context))
        first = next((c for c in contexts if c["street"] == "preflop" and c["move"]["action"] != "fold"), None)
        if first and line_of(row) and (hand.pk, first["step"], "their_range") not in taken:
            reads_found.append((hand, data, row, first))
    moves.sort(key=lambda item: item[0], reverse=True)
    rng.shuffle(reads_found)
    chosen = [
        action_scenario(user, hand, data, row.name, context, rules) for _, hand, data, row, context in moves[:actions]
    ]
    for hand, data, row, context in reads_found:
        if len([found for found in chosen if found.topic == "their_range"]) >= reads:
            break
        if scenario := range_scenario(user, hand, data, row, context, typical_rates):
            chosen.append(scenario)
    return chosen


@transaction.atomic
def their_set(user, day, rng=None):
    """A set of spots from opponents' seats: their moves first, their ranges after."""
    rng = rng or random.Random()
    found = spots(user, rng, actions=DAILY_SIZE - 3, reads=3)
    return save_set(user, "their_seat", day, [(scenario, False) for scenario in found[:DAILY_SIZE]])
