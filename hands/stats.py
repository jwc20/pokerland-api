"""What the web app shows about a user's hands: results per day and per tag, and the hero's statistics."""

import datetime
import math

from django.db.models import Case, CharField, Count, F, FloatField, Max, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, NullIf, TruncDate, TruncMonth

from hands import ranges
from hands.filters import FORMAT, stakes_value, tag_key
from hands.models import HandBet, HandPlayer
from tracker.parsing.facts import ALL_HAND_GROUPS, POSTFLOP_ACTIONS, STATS

# How a 95% interval reaches either side of an estimate, in standard errors.
Z95 = 1.96
# Positions from the first to act before the flop to the last; any other sorts after them.
POSITION_ORDER = ("UTG", "UTG+1", "UTG+2", "UTG+3", "UTG+4", "LJ", "HJ", "CO", "BTN", "SB", "BB")
# What /api/stats/ can group the hero's hands by (FND-4). Stakes are cash games' alone, since tournament blinds go up
# every level, and the M zone tournaments' alone.
STAT_GROUPINGS = (
    "none",
    "position",
    "month",
    "stakes",
    "situation",
    "stack_depth",
    "m_zone",
    "hand_group",
    "combo",
    "bet_size",
    "opponent",
)
SITUATION_ORDER = ("unopened", "limped", "raised", "3bet", "4bet+", "none")
# Effective stacks in big blinds, from short to deep [MIT 2: the stack-size report; JHU 6], each (key, from, to).
STACK_DEPTHS = (("0-10", None, 10), ("10-20", 10, 20), ("20-40", 20, 40), ("40-100", 40, 100), ("100+", 100, None))
# The MIT course's M zones [MIT 5]: dead, push or fold, steal and re-steal, value-betting, set-mining.
M_ZONES = (("dead", None, 2), ("push_fold", 2, 8), ("restealing", 8, 12), ("value", 12, 30), ("set_mining", 30, None))
# The hero's biggest bet or raise after the flop, as a share of what was in the middle [B4].
BET_SIZES = (
    ("under_third", None, 0.33),
    ("third_half", 0.33, 0.5),
    ("half_three_quarters", 0.5, 0.75),
    ("three_quarters_pot", 0.75, 0.99),
    ("pot_plus", 0.99, None),
)
BET_SIZE_KEYS = tuple(key for key, _, _ in BET_SIZES)
FIRST_ACTIONS = ("fold", "check", "call", "raise")
OPPONENT_GROUPS = 50  # the opponents grouping's default: the players the hero played most hands with


def hand_bb():
    """A hand's result in big blinds."""
    return Cast("hero_net", FloatField()) / Cast("big_blind", FloatField())


def net_bb():
    """The hands' results summed in big blinds, which add up across stakes and currencies where chips and cents don't.

    A hand without a big blind adds nothing rather than dividing by zero.
    """
    return Sum(hand_bb(), filter=Q(big_blind__gt=0), default=0.0)


def net_bb_squares():
    """The squares of the hands' results in big blinds, summed: with `net_bb`, what their spread comes from."""
    return Sum(hand_bb() * hand_bb(), filter=Q(big_blind__gt=0), default=0.0)


def results():
    """Aggregates for a set of hands: how many there are, how many were won and lost, and the net in big blinds."""
    return {
        "hands": Count("id"),
        "won": Count("id", filter=Q(hero_net__gt=0)),
        "lost": Count("id", filter=Q(hero_net__lt=0)),
        "net_bb": net_bb(),
        "net_bb_squares": net_bb_squares(),
    }


def sample_stdev(count, total, squares):
    """The sample standard deviation of `count` values, from their sum and the sum of their squares.

    As PokerKit's `Statistics.payoff_stdev` computes it, dividing by count - 1;
    None for fewer than two values.
    """
    if count < 2:
        return None
    return math.sqrt(max(0.0, (squares - total * total / count) / (count - 1)))  # rounding can dip below zero


def played_days(hands, tz):
    """The days in `tz` with any of `hands`, oldest first, as {day, hands, net_bb}."""
    return (
        hands.annotate(day=TruncDate("played_at", tzinfo=tz))
        .values("day")
        .annotate(hands=Count("id"), net_bb=net_bb())
        .order_by("day")
    )


def streaks(days, today):
    """The current and the longest run of consecutive dates in `days`, which are in order.

    The current run ends today, or yesterday while today has none yet: it lasts
    until the day is out.
    """
    one_day = datetime.timedelta(days=1)
    best = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous is not None and day - previous == one_day else 1
        best = max(best, run)
        previous = day
    if previous is None or today - previous > one_day:
        return 0, best
    return run, best


def tag_stats(hands):
    """`hands` counted per tag: all of them first, then the position, game, cash stakes and format tags by count."""
    tags = []
    for row in hands.exclude(hero_position="").values("hero_position").annotate(**results()).order_by():
        tags.append(_tag("position", row.pop("hero_position"), row))
    for row in hands.values("game").annotate(**results()).order_by():
        tags.append(_tag("game", row.pop("game"), row))
    # Tournament blinds go up every level, so only cash games have stakes.
    stakes_rows = hands.filter(tournament_id="").values("currency", "small_blind", "big_blind")
    for row in stakes_rows.annotate(**results()).order_by():
        stakes = {name: row.pop(name) for name in ("currency", "small_blind", "big_blind")}
        tags.append(_tag("stakes", stakes_value(**stakes), row, stakes))
    for row in hands.annotate(format=FORMAT).values("format").annotate(**results()).order_by():
        tags.append(_tag("format", row.pop("format"), row))
    tags.sort(key=lambda tag: (-tag["hands"], tag["group"], tag["value"]))
    return [_tag("all", "", hands.aggregate(**results())), *tags]


def _tag(group, value, counts, stakes=None):
    stdev = sample_stdev(counts["hands"], counts["net_bb"], counts["net_bb_squares"])
    return {
        "key": tag_key(group, value),
        "group": group,
        "value": value,
        "stakes": stakes,
        "hands": counts["hands"],
        "won": counts["won"],
        "lost": counts["lost"],
        "net_bb": round(counts["net_bb"], 2),
        "bb_stdev": None if stdev is None else round(stdev, 2),
    }


def proportion(did, could):
    """`did` out of `could` in percent, with its 95% Wilson interval; no share without a chance.

    Wilson's interval stays inside 0–100% and stays honest for small samples,
    where did ÷ could ± 1.96 standard errors would not.
    """
    if not could:
        return {"did": did, "could": 0, "pct": None, "ci_low": None, "ci_high": None}
    share = did / could
    spread = Z95 * Z95 / could
    centre = (share + spread / 2) / (1 + spread)
    half = Z95 * math.sqrt(share * (1 - share) / could + spread / (4 * could)) / (1 + spread)
    return {
        "did": did,
        "could": could,
        "pct": round(100 * share, 1),
        "ci_low": round(100 * max(0.0, centre - half), 1),
        "ci_high": round(100 * min(1.0, centre + half), 1),
    }


def _chips(column):
    return Cast(column, FloatField())


def rake_share():
    """A HandPlayer's share of their hand's rake, in big blinds: the rake split by what each player put in.

    So a player pays some of the rake in a pot they lose: the "weighted
    contributed" way of counting it. Nothing for a hand without a pot.
    """
    return _chips("hand__rake") * F("invested_bb") / NullIf(_chips("hand__total_pot"), 0.0)


def rake_from_wins():
    """The rake taken from what a HandPlayer won, in big blinds: added back, their result had there been no rake.

    The rake comes out of every pot at the same rate (tracker.parsing.pokerstars.rake_by_pot),
    so a winner's part of it is the rake × their share of what all the winners got.
    """
    won = F("invested_bb") + F("net_bb")
    return _chips("hand__rake") * won / NullIf(_chips(F("hand__total_pot") - F("hand__rake")), 0.0)


def with_hero_all_in(hands):
    """`hands` with their hero's equity when the money went in before the river, `hero_allin_equity` (null in
    every other hand), and the net they could expect then, `hero_ev_net_bb`."""
    hero = HandPlayer.objects.filter(hand=OuterRef("pk"), is_hero=True)
    return hands.annotate(
        hero_allin_equity=Subquery(hero.values("allin_equity")[:1]),
        hero_ev_net_bb=Subquery(hero.values("ev_net_bb")[:1]),
    )


def bucketed(column, buckets):
    """A Case naming the bucket `column`'s value falls in, from (key, from, to) triples: from it, up to but not
    including the next."""
    whens = []
    for key, low, high in buckets:
        condition = Q()
        if low is not None:
            condition &= Q(**{f"{column}__gte": low})
        if high is not None:
            condition &= Q(**{f"{column}__lt": high})
        whens.append(When(condition, then=Value(key)))
    return Case(*whens, default=Value(""), output_field=CharField())


def _grouped(rows, key, sums, order):
    """`rows` summed by `key`, the groups in `order` (keys outside it after, by name), without the empty key."""
    found = [(row.pop("key"), row) for row in rows.annotate(key=key).values("key").annotate(**sums).order_by()]
    rank = {name: i for i, name in enumerate(order)}
    found = [(name, row) for name, row in found if name not in ("", None)]
    return sorted(found, key=lambda group: (rank.get(group[0], len(rank)), str(group[0])))


def hero_stats(hands, group_by="none", tz=None, limit=OPPONENT_GROUPS):
    """The hero's statistics over `hands`, in one group or one per key of `group_by` (STAT_GROUPINGS): position,
    month in `tz`, cash stakes, preflop situation, effective stack, M zone, starting-hand group or combo, the size
    of their biggest bet after the flop, or the opponent dealt in (the `limit` they played most hands with; a hand
    counts for each of its opponents).

    Each group has its hands, their net and its spread in big blinds (as the
    tags have them), the rake (`rake_share`, and the net before it), the net
    adjusted for all-in equity with its all-ins, how the hero's first decision
    before the flop went, how often they moved in when they raised it, and every
    statistic of tracker.parsing.facts.STATS as a proportion, with the
    aggression frequency after the flop: (bets + raises) ÷ (bets + raises +
    calls + folds).
    """
    rows = HandPlayer.objects.filter(is_hero=True, hand__in=hands)
    counted = [f"{stat}_{part}" for stat in STATS for part in ("could", "did")]
    counted += [f"postflop_{action}" for action in POSTFLOP_ACTIONS]
    # Named apart from the columns, which an aggregate may not shadow.
    sums = {
        "hands": Count("id"),
        "total_bb": Sum("net_bb", default=0.0),
        "total_bb_squares": Sum(F("net_bb") * F("net_bb"), default=0.0),
        "total_rake_bb": Sum(rake_share(), default=0.0),
        "total_rake_from_wins_bb": Sum(rake_from_wins(), default=0.0),
        # A4: the net expected when the money went in before the river, else the net.
        "total_ev_bb": Sum(Coalesce("ev_net_bb", "net_bb"), default=0.0),
        "total_all_ins": Count("id", filter=Q(ev_net_bb__isnull=False)),
        # The first decision before the flop, and raises that moved in.
        **{f"total_first_{action}": Count("id", filter=Q(first_action=action)) for action in FIRST_ACTIONS},
        "total_raised": Count("id", filter=Q(first_raise_all_in__isnull=False)),
        "total_shoved": Count("id", filter=Q(first_raise_all_in=True)),
        **{f"total_{column}": Sum(column, default=0) for column in counted},
    }
    groups = _groups(rows, group_by, tz, sums, limit)
    return [_stat_group(key, totals) for key, totals in groups]


def _groups(rows, group_by, tz, sums, limit):
    """The (key, sums) pairs of `rows` grouped by `group_by`."""
    if group_by == "situation":
        situation = Case(When(situation="", then=Value("none")), default=F("situation"), output_field=CharField())
        return _grouped(rows, situation, sums, SITUATION_ORDER)
    if group_by == "stack_depth":
        return _grouped(rows, bucketed("hand__effective_bb", STACK_DEPTHS), sums, [key for key, _, _ in STACK_DEPTHS])
    if group_by == "m_zone":
        zoned = rows.filter(hand__hero_m__isnull=False)
        return _grouped(zoned, bucketed("hand__hero_m", M_ZONES), sums, [key for key, _, _ in M_ZONES])
    if group_by == "combo":
        return _grouped(rows.exclude(hand__hero_combo=""), F("hand__hero_combo"), sums, ())
    if group_by == "hand_group":
        return _hand_groups(rows, sums)
    if group_by == "bet_size":
        biggest = HandBet.objects.filter(hand=OuterRef("hand"), is_hero=True, street__in=("flop", "turn", "river"))
        sized = rows.annotate(biggest=Subquery(biggest.values("hand").annotate(top=Max("size")).values("top")[:1]))
        return _grouped(sized, bucketed("biggest", BET_SIZES), sums, [key for key, _, _ in BET_SIZES])
    if group_by == "opponent":
        # One join to the opponents' rows, in one filter() so the key and the sums share it.
        shared = rows.filter(hand__seats__is_hero=False)
        found = shared.annotate(key=F("hand__seats__name")).values("key").annotate(**sums).order_by("-hands", "key")
        return [(row.pop("key"), row) for row in found[:limit]]
    if group_by == "position":
        groups = [(row.pop("position"), row) for row in rows.values("position").annotate(**sums).order_by()]
        rank = {position: i for i, position in enumerate(POSITION_ORDER)}
        groups.sort(key=lambda group: (rank.get(group[0], len(rank)), group[0]))
    elif group_by == "month":
        months = rows.annotate(month=TruncMonth("hand__played_at", tzinfo=tz)).values("month").annotate(**sums)
        groups = [(row.pop("month").strftime("%Y-%m"), row) for row in months.order_by("month")]
    elif group_by == "stakes":
        blinds = ("hand__currency", "hand__big_blind", "hand__small_blind")  # chips first, then by size
        cash = rows.filter(hand__tournament_id="").values(*blinds).annotate(**sums).order_by(*blinds)
        groups = [
            (stakes_value(row.pop("hand__currency"), row.pop("hand__small_blind"), row.pop("hand__big_blind")), row)
            for row in cash
        ]
    else:
        groups = [("all", rows.aggregate(**sums))]
    return groups


def _hand_groups(rows, sums):
    """The combos' sums gathered into the JHU starting-hand groups (tracker.parsing.facts.hand_group)."""
    totals = {}
    for combo, row in _grouped(rows.exclude(hand__hero_combo=""), F("hand__hero_combo"), sums, ()):
        group = ranges.group_of(combo)
        if group in totals:
            totals[group] = {name: totals[group][name] + value for name, value in row.items()}
        else:
            totals[group] = row
    return [(group, totals[group]) for group in ALL_HAND_GROUPS if group in totals]


def _stat_group(key, sums):
    total = {column.removeprefix("total_"): value for column, value in sums.items()}
    stdev = sample_stdev(total["hands"], total["bb"], total["bb_squares"])
    stats = {stat: proportion(total[f"{stat}_did"], total[f"{stat}_could"]) for stat in STATS}
    aggressive = total["postflop_bets"] + total["postflop_raises"]
    stats["aggression"] = proportion(aggressive, aggressive + total["postflop_calls"] + total["postflop_folds"])
    return {
        "key": key,
        "first_actions": {action: proportion(total[f"first_{action}"], total["hands"]) for action in FIRST_ACTIONS},
        "shove": proportion(total["shoved"], total["raised"]),
        "hands": total["hands"],
        "net_bb": round(total["bb"], 2),
        "bb_stdev": None if stdev is None else round(stdev, 2),
        "rake_bb": round(total["rake_bb"], 2),
        "net_before_rake_bb": round(total["bb"] + total["rake_from_wins_bb"], 2),
        "ev_net_bb": round(total["ev_bb"], 2),
        "all_ins": total["all_ins"],
        "stats": stats,
    }
