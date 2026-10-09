"""Reference ranges: the published charts preflop spots are graded by, and how a range answer is scored
(pokerland-practice-mode.md, 4.4 and 5).

A spot graded by a chart ("reference" grading) shows the chart and the hand's cell beside the answer, so a user who
disagrees disagrees with a chart they can see, not with an oracle.

**The chart** is the MIT course's value-zone ranges, for a tournament stack with an M of 12 to 30 at a full table
[MIT 5]:

- early position (UTG to UTG+2): about the top 5%, tens or better, ace-queen suited or better and ace-king;
- middle position (the lojack and the hijack): about 15%, eights or better, ace-jack or better and king-queen;
- facing a raise, move up a tier: from middle position, the early-position range.

The lecture gives no ranges for the cutoff, the button or the blinds, nor a tier above early position's, so no spot
asks about those. It rounds for teaching (risk 9 of the feature ideas): the early range is 3.8% of hands and the
middle one 8.0%, and the feedback shows the exact share beside the lecture's figure. Never open-limp [JHU 3]:
limping first in with a hand the chart plays is acceptable, at half credit; with any other hand it is poor.

**A range answer** ("which hands does this line represent?") is scored by its overlap with the stated range, by
combos: the combos in both ÷ the combos in either. Partial credit, as the main doc's hand-reading row asks.

Django-free, like the rest of the engine.
"""

from hands.ranges import combos_of, parse

CHART = {
    "key": "mit5_value_zone",
    "label": "MIT 15.S50 value-zone ranges",
    "applies_to": "A full table in a tournament, with an M of 12 to 30",
    "source": "MIT 5",
}
# Each tier, tightest first: its range, what the lecture calls it, and its source.
TIERS = {
    "early": ("TT+, AQs+, AK", "Tens or better, ace-queen suited or better, ace-king", "about the top 5%", "MIT 5"),
    "middle": ("88+, AJ+, KQ", "Eights or better, ace-jack or better, king-queen", "about the top 15%", "MIT 5"),
}
# The course's memory aids for ranges as percentiles [MIT 4], which a range answer is compared with.
ANCHORS = {
    1: "AA, KK, AK",
    5: "TT+, AQ+",
    10: "22+, AT+",
    20: "22+, A2+",
    30: "22+, A2+, KT+, QT+, JT",
}
ORDER = tuple(TIERS)
# The seats the chart covers, at a table of nine, and each one's tier when the pot is unopened.
SEATS = {"UTG": "early", "UTG+1": "early", "UTG+2": "early", "LJ": "middle", "HJ": "middle"}
SEAT_NAMES = {
    "UTG": "under the gun",
    "UTG+1": "UTG+1",
    "UTG+2": "UTG+2",
    "LJ": "the lojack",
    "HJ": "the hijack",
    "CO": "the cutoff",
    "BTN": "the button",
    "SB": "the small blind",
    "BB": "the big blind",
}
M_ZONE = (12, 30)
# A range answer's overlap from which it is good, and from which it is acceptable.
GOOD_OVERLAP, FAIR_OVERLAP = 0.7, 0.45


def tier_for(position, facing_raise=False):
    """The tier a seat plays: its own when the pot is unopened, the next one up facing a raise. None where the chart
    says nothing, as from the cutoff on, or facing a raise in early position."""
    tier = SEATS.get(position)
    if tier is None or not facing_raise:
        return tier
    above = ORDER.index(tier) - 1
    return ORDER[above] if above >= 0 else None


def hands_of(tier):
    return parse(TIERS[tier][0])


def chart_of(tier):
    """A tier as the feedback shows it: the chart, the tier's range, what the lecture calls it and its exact share."""
    notation, label, claimed, source = TIERS[tier]
    return {
        **CHART,
        "tier": tier,
        "range": notation,
        "tier_label": label,
        "claimed": claimed,
        "tier_source": source,
        "share": round(combos_of(hands_of(tier)) / 1326, 4),
    }


def answer(hand, tier, facing_raise):
    """What the chart says of a hand: the best moves, the acceptable ones, and whether it is in the range.

    Unopened, a hand in the range raises, and limping it is acceptable; any other hand folds. Facing a raise, a hand
    in the tier above continues, by a call or a re-raise alike: the lecture says which hands, not how.
    """
    inside = hand in hands_of(tier)
    if not inside:
        return {"best": ["fold"], "acceptable": [], "in_range": False}
    if facing_raise:
        return {"best": ["raise", "call"], "acceptable": [], "in_range": True}
    return {"best": ["raise"], "acceptable": ["call"], "in_range": True}


def overlap(chosen, reference):
    """How a range answer meets the stated range, by combos: in both, only in the answer, only in the reference."""
    chosen, reference = set(chosen), set(reference)
    return {
        "both": combos_of(chosen & reference),
        "extra": combos_of(chosen - reference),
        "missed": combos_of(reference - chosen),
    }


def overlap_score(chosen, reference):
    """The combos in both ÷ the combos in either: 1 for the stated range exactly, 0 for nothing in common."""
    parts = overlap(chosen, reference)
    either = parts["both"] + parts["extra"] + parts["missed"]
    return parts["both"] / either if either else 1.0


def nearest_anchor(percent):
    """The course's memory aid nearest a share of hands, as (its percent, its range)."""
    near = min(ANCHORS, key=lambda anchor: abs(anchor - percent))
    return near, ANCHORS[near]


def range_grade(score):
    """A range answer's grade from its overlap score."""
    if score >= GOOD_OVERLAP:
        return "good"
    return "acceptable" if score >= FAIR_OVERLAP else "poor"
