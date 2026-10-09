"""Reports over the hero's hands that aren't did ÷ could alone: bet sizing and its tells (B4 of the feature ideas),
and how they played each street after the flop (B6).

- `sizing`: the hero's bets and raises after the flop by street and size, each split by how strong their hand was
  (tracker.parsing.facts.STRENGTHS), the size that says most about their hand, and the flags their sizes raised.
  Value bets should be the biggest a worse hand calls and bluffs the smallest that works, but sizing by strength
  gives a hand away [JHU 5; MIT 8], and bet-sizing tells are more reliable than physical ones [JHU 8].
- `lines`: the flop, turn and river by the hero's part before the flop (raised, called, or limped) and whether
  they had position: how often they bet when they could have, and how they answered a bet, by the board's
  texture [JHU 5: the aggressor-by-position matrix]; then barrels after a called c-bet [JHU 8].
"""

from collections import defaultdict

from django.db.models import Count, Q

from hands.models import HandBet
from hands.stats import BET_SIZES, bucketed, proportion
from tracker.parsing.facts import SIZING_FLAGS, STRENGTHS, TEXTURES

POSTFLOP = ("flop", "turn", "river")
STRONG = ("strong", "nuts")
MIN_TELL = 10  # a size needs this many bets of known strength before it can tell anything


def sizing(hands):
    """The hero's bets and raises after the flop in `hands`, by street and size bucket (hands.stats.BET_SIZES)."""
    bets = HandBet.objects.filter(hand__in=hands, is_hero=True, street__in=POSTFLOP, size__isnull=False)
    counted = (
        bets.annotate(bucket=bucketed("size", BET_SIZES))
        .values("street", "bucket", "strength")
        .annotate(bets=Count("id"))
        .order_by()
    )
    cells = defaultdict(lambda: defaultdict(lambda: dict.fromkeys(STRENGTHS, 0)))
    for row in counted:
        if row["strength"] in STRENGTHS:
            cells[row["street"]][row["bucket"]][row["strength"]] += row["bets"]
    streets = []
    for street in POSTFLOP:
        if street not in cells:
            continue
        buckets = []
        for key, _, _ in BET_SIZES:
            strengths = cells[street].get(key)
            if strengths:
                total = sum(strengths.values())
                strong = sum(strengths[name] for name in STRONG)
                buckets.append({"key": key, "bets": total, "strengths": strengths, "strong": proportion(strong, total)})
        everything = sum(bucket["bets"] for bucket in buckets)
        strong = sum(bucket["strong"]["did"] for bucket in buckets)
        overall = proportion(strong, everything)
        streets.append(
            {"street": street, "bets": everything, "strong": overall, "tell": _tell(buckets, overall), "buckets": buckets}
        )
    hero_bets = hands.filter(bets__is_hero=True, bets__street__in=POSTFLOP).distinct().count()
    flags = [
        {"flag": flag, "hands": hands.filter(facts__hero__flags__icontains=f'"{flag}"').count(), "of": hero_bets}
        for flag in SIZING_FLAGS
    ]
    return {"streets": streets, "flags": flags}


def _tell(buckets, overall):
    """The size whose share of strong hands is furthest from the street's share, among those with MIN_TELL bets:
    what that size says about the hand. None when no size has the bets to say."""
    candidates = [bucket for bucket in buckets if bucket["bets"] >= MIN_TELL]
    if len(candidates) < 2 or overall["pct"] is None:
        return None
    furthest = max(candidates, key=lambda bucket: abs(bucket["strong"]["pct"] - overall["pct"]))
    gap = round(furthest["strong"]["pct"] - overall["pct"], 1)
    return {"bucket": furthest["key"], "strong": furthest["strong"], "gap": gap}


def lines(hands):
    """How the hero played the flop, turn and river in `hands`: per street, by their part before the flop and
    position, then by texture; and the turn and river after a called c-bet."""
    counts = {street: defaultdict(lambda: defaultdict(int)) for street in POSTFLOP}
    barrels = {street: defaultdict(int) for street in ("turn", "river")}
    for played in hands.exclude(facts__hero__lines__isnull=True).values_list("facts__hero__lines", flat=True):
        if not played:
            continue
        for street, line in played.items():
            if street not in counts:
                continue
            for key in ((line["role"], line["ip"], None), (line["role"], line["ip"], line["texture"])):
                tally = counts[street][key]
                tally["hands"] += 1
                if line["first"]:
                    tally[line["first"]] += 1
                if line["faced"]:
                    tally["faced"] += 1
                    tally[f"faced_{line['faced']}"] += 1
        for previous, street in (("flop", "turn"), ("turn", "river")):
            _barrel(played.get(previous), played.get(street), barrels[street])
    return {
        "streets": [
            {"street": street, "spots": _spots(counts[street])} for street in POSTFLOP if counts[street]
        ],
        "barrels": [
            {"street": street, **_barrel_row(tally), "sizes": river_sizes(hands) if street == "river" else []}
            for street, tally in barrels.items()
            if tally
        ],
    }


def _spots(tallies):
    """Each (part, position) with its moves, then its moves by texture."""
    order = {("raised", True): 0, ("raised", False): 1, ("called", True): 2, ("called", False): 3}
    spots = []
    for (role, ip, texture), tally in tallies.items():
        if texture is not None:
            continue
        textures = [
            {"texture": name, **_moves(tallies[(role, ip, name)])}
            for name in TEXTURES
            if (role, ip, name) in tallies
        ]
        spots.append({"role": role, "ip": ip, **_moves(tally), "textures": textures})
    spots.sort(key=lambda spot: (order.get((spot["role"], spot["ip"]), 9), spot["role"], str(spot["ip"])))
    return spots


def _moves(tally):
    first = tally["bet"] + tally["check"]
    faced = tally["faced"]
    return {
        "hands": tally["hands"],
        "bet": proportion(tally["bet"], first),
        "fold": proportion(tally["faced_fold"], faced),
        "call": proportion(tally["faced_call"], faced),
        "raise": proportion(tally["faced_raise"], faced),
    }


def _barrel(previous, line, tally):
    """Counts the street after a c-bet that was called: barrel, check behind, or check and then answer a bet."""
    if not previous or not line or previous["role"] != "raised":
        return
    if previous["first"] != "bet" or previous["outcome"] != "called":
        return
    tally["hands"] += 1
    if line["first"] == "bet":
        tally["barrel"] += 1
    elif line["first"] == "check":
        tally["checked_behind" if line["ip"] else "checked"] += 1
        if line["faced"]:
            tally[f"then_{line['faced']}"] += 1


def _barrel_row(tally):
    chances = tally["barrel"] + tally["checked_behind"] + tally["checked"]
    checked = tally["checked"]
    return {
        "hands": tally["hands"],
        "barrel": proportion(tally["barrel"], chances),
        "checked_behind": proportion(tally["checked_behind"], chances),
        "gave_up": proportion(tally["then_fold"], checked),
        "check_call": proportion(tally["then_call"], checked),
        "check_raise": proportion(tally["then_raise"], checked),
    }


def river_sizes(hands):
    """The hero's river bets after betting the flop and the turn, by size bucket: the third barrel's sizes."""
    barrelled = Q(hand__facts__hero__lines__flop__first="bet", hand__facts__hero__lines__turn__first="bet")
    rows = (
        HandBet.objects.filter(barrelled, hand__in=hands, is_hero=True, street="river", kind="bet")
        .annotate(bucket=bucketed("size", BET_SIZES))
        .values("bucket")
        .annotate(bets=Count("id"))
        .order_by()
    )
    found = {row["bucket"]: row["bets"] for row in rows}
    return [{"key": key, "bets": found[key]} for key, _, _ in BET_SIZES if key in found]
