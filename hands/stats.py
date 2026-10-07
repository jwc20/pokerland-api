"""What the web app's home page shows about a user's hands: results per day and per tag."""

import datetime

from django.db.models import Count, FloatField, Q, Sum
from django.db.models.functions import Cast, TruncDate

from hands.filters import FORMAT, stakes_value, tag_key


def net_bb():
    """The hands' results summed in big blinds, which add up across stakes and currencies where chips and cents don't.

    A hand without a big blind adds nothing rather than dividing by zero.
    """
    return Sum(
        Cast("hero_net", FloatField()) / Cast("big_blind", FloatField()),
        filter=Q(big_blind__gt=0),
        default=0.0,
    )


def results():
    """Aggregates for a set of hands: how many there are, how many were won and lost, and the net in big blinds."""
    return {
        "hands": Count("id"),
        "won": Count("id", filter=Q(hero_net__gt=0)),
        "lost": Count("id", filter=Q(hero_net__lt=0)),
        "net_bb": net_bb(),
    }


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
    return {
        "key": tag_key(group, value),
        "group": group,
        "value": value,
        "stakes": stakes,
        "hands": counts["hands"],
        "won": counts["won"],
        "lost": counts["lost"],
        "net_bb": round(counts["net_bb"], 2),
    }
