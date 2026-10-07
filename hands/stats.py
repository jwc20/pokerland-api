"""What the web app shows about a user's hands: results per day and per tag, and the hero's statistics."""

import datetime
import math

from django.db.models import Count, F, FloatField, Q, Sum
from django.db.models.functions import Cast, TruncDate, TruncMonth

from hands.filters import FORMAT, stakes_value, tag_key
from hands.models import HandPlayer
from tracker.parsing.facts import POSTFLOP_ACTIONS, STATS

# How a 95% interval reaches either side of an estimate, in standard errors.
Z95 = 1.96
# Positions from the first to act before the flop to the last; any other sorts after them.
POSITION_ORDER = ("UTG", "UTG+1", "UTG+2", "UTG+3", "UTG+4", "LJ", "HJ", "CO", "BTN", "SB", "BB")
# What /api/stats/ can group the hero's hands by.
STAT_GROUPINGS = ("none", "position", "month")


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


def hero_stats(hands, group_by="none", tz=None):
    """The hero's statistics over `hands`, in one group, or one per position or per month in `tz`.

    Each group has its hands, their net and its spread in big blinds (as the
    tags have them), and every statistic of tracker.parsing.facts.STATS as a
    proportion, with the aggression frequency after the flop:
    (bets + raises) ÷ (bets + raises + calls + folds).
    """
    rows = HandPlayer.objects.filter(is_hero=True, hand__in=hands)
    counted = [f"{stat}_{part}" for stat in STATS for part in ("could", "did")]
    counted += [f"postflop_{action}" for action in POSTFLOP_ACTIONS]
    # Named apart from the columns, which an aggregate may not shadow.
    sums = {
        "hands": Count("id"),
        "total_bb": Sum("net_bb", default=0.0),
        "total_bb_squares": Sum(F("net_bb") * F("net_bb"), default=0.0),
        **{f"total_{column}": Sum(column, default=0) for column in counted},
    }
    if group_by == "position":
        groups = [(row.pop("position"), row) for row in rows.values("position").annotate(**sums).order_by()]
        rank = {position: i for i, position in enumerate(POSITION_ORDER)}
        groups.sort(key=lambda group: (rank.get(group[0], len(rank)), group[0]))
    elif group_by == "month":
        months = rows.annotate(month=TruncMonth("hand__played_at", tzinfo=tz)).values("month").annotate(**sums)
        groups = [(row.pop("month").strftime("%Y-%m"), row) for row in months.order_by("month")]
    else:
        groups = [("all", rows.aggregate(**sums))]
    return [_stat_group(key, totals) for key, totals in groups]


def _stat_group(key, sums):
    total = {column.removeprefix("total_"): value for column, value in sums.items()}
    stdev = sample_stdev(total["hands"], total["bb"], total["bb_squares"])
    stats = {stat: proportion(total[f"{stat}_did"], total[f"{stat}_could"]) for stat in STATS}
    aggressive = total["postflop_bets"] + total["postflop_raises"]
    stats["aggression"] = proportion(aggressive, aggressive + total["postflop_calls"] + total["postflop_folds"])
    return {
        "key": key,
        "hands": total["hands"],
        "net_bb": round(total["bb"], 2),
        "bb_stdev": None if stdev is None else round(stdev, 2),
        "stats": stats,
    }
