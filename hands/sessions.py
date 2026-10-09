"""Sessions (F1 of the feature ideas): a user's hands grouped into stretches of play by the gaps between them.

A gap of more than GAP between one hand and the next, at any table, starts a new session. `assign` rebuilds the
sessions around newly stored hands. It keeps the row of a session that carries on, so its id and links last, and
it notes each hand's session, its hour into it, and how many tables were open then: multi-tabling shows as tables
whose stretches of hands overlap. `patterns` sets results against those, the time of day and the day of the week,
since part of the metagame is deciding whether to play at all [MIT 1].
"""

import datetime
from collections import defaultdict

from django.db.models import Count, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce, ExtractHour, ExtractIsoWeekDay

from hands import results
from hands.filters import PLAYED
from hands.models import Hand, HandPlayer, Session
from hands.stats import sample_stdev

GAP = datetime.timedelta(minutes=30)
# Hours of the day, in the user's time zone, by the part of it they fall in.
TIMES_OF_DAY = (
    ("night", range(0, 6)),
    ("morning", range(6, 12)),
    ("afternoon", range(12, 18)),
    ("evening", range(18, 24)),
)
WRITE_BATCH = 1000


def assign(user_id, times):
    """Rebuilds `user_id`'s sessions around hands played at `times`, which have just been stored."""
    if not times:
        return
    lo, hi = min(times) - GAP, max(times) + GAP
    old = list(Session.objects.filter(user_id=user_id, end__gte=lo, start__lte=hi).order_by("start", "id"))
    if old:
        lo, hi = min(lo, old[0].start), max(hi, max(session.end for session in old))
    hero = HandPlayer.objects.filter(hand=OuterRef("pk"), is_hero=True)
    hands = list(
        Hand.objects.filter(PLAYED, user_id=user_id, played_at__gte=lo, played_at__lte=hi)
        .annotate(hero_ev=Subquery(hero.values("ev_net_bb")[:1]))
        .order_by("played_at", "id")
        .only("id", "played_at", "table", "hero_net", "big_blind", "total_pot")
    )
    runs = []
    for hand in hands:
        if runs and hand.played_at - runs[-1][-1].played_at <= GAP:
            runs[-1].append(hand)
        else:
            runs.append([hand])

    unused = list(old)
    for run in runs:
        reuse = next((s for s in unused if s.start <= run[-1].played_at and s.end >= run[0].played_at), None)
        session = reuse or Session(user_id=user_id)
        if reuse:
            unused.remove(reuse)
        _fill(session, run)
        session.save()
        for hand in run:
            hand.session = session
    Session.objects.filter(pk__in=[session.pk for session in unused]).delete()
    Hand.objects.bulk_update(hands, ("session", "session_hour", "tables_open"), batch_size=WRITE_BATCH)


def _fill(session, run):
    """Sets a session's span and counts from its hands, oldest first, and each hand's hour and open tables."""
    session.start, session.end = run[0].played_at, run[-1].played_at
    spans = {}
    for hand in run:
        first, _ = spans.get(hand.table, (hand.played_at, None))
        spans[hand.table] = (first, hand.played_at)
    net = [hand.hero_net / hand.big_blind if hand.big_blind else 0.0 for hand in run]
    for hand in run:
        hand.session_hour = int((hand.played_at - session.start).total_seconds() // 3600)
        hand.tables_open = sum(1 for first, last in spans.values() if first <= hand.played_at <= last)
    session.hands = len(run)
    session.tables = len(spans)
    session.most_tables = max(hand.tables_open for hand in run)
    session.net_bb = sum(net)
    session.net_bb_squares = sum(bb * bb for bb in net)
    session.ev_net_bb = sum(bb if hand.hero_ev is None else hand.hero_ev for hand, bb in zip(run, net, strict=True))
    session.biggest_pot_bb = max(hand.total_pot / hand.big_blind if hand.big_blind else 0.0 for hand in run)


def rebuild(user_id):
    """Builds every one of the user's sessions afresh, e.g. once hands were stored before sessions were."""
    results.changed(user_id)
    Session.objects.filter(user_id=user_id).delete()
    span = Hand.objects.filter(PLAYED, user_id=user_id).order_by("played_at").values_list("played_at", flat=True)
    if span.exists():
        assign(user_id, [span.first(), span.last()])


def patterns(hands, tz):
    """The hero's results in `hands` by their hour into the session, the time of day and the day of the week in
    `tz`, and the tables open at once: each group's hands, net and spread in big blinds, and net adjusted for
    all-in equity."""
    rows = HandPlayer.objects.filter(is_hero=True, hand__in=hands, hand__session__isnull=False)

    def hour_in(hour):
        return "3+" if hour >= 3 else str(hour)

    def part_of_day(hour):
        return next(name for name, hours in TIMES_OF_DAY if hour in hours)

    def tables(count):
        return "4+" if count >= 4 else str(count)

    return {
        "hours_in": _grouped(rows, F("hand__session_hour"), hour_in, ["0", "1", "2", "3+"]),
        "time_of_day": _grouped(
            rows, ExtractHour("hand__played_at", tzinfo=tz), part_of_day, [name for name, _ in TIMES_OF_DAY]
        ),
        "weekday": _grouped(rows, ExtractIsoWeekDay("hand__played_at", tzinfo=tz), str, [str(d) for d in range(1, 8)]),
        "tables": _grouped(rows, F("hand__tables_open"), tables, ["1", "2", "3", "4+"]),
    }


def _grouped(rows, key, bucket, order):
    """`rows` summed by `key`, its values gathered into buckets by `bucket`, in the buckets' `order`."""
    sums = {
        "hands": Count("id"),
        "bb": Sum("net_bb", default=0.0),
        "squares": Sum(F("net_bb") * F("net_bb"), default=0.0),
        "ev": Sum(Coalesce("ev_net_bb", "net_bb"), default=0.0),
    }
    totals = defaultdict(lambda: dict.fromkeys(sums, 0))
    for row in rows.annotate(key=key).values("key").annotate(**sums).order_by():
        total = totals[bucket(row["key"])]
        for name in sums:
            total[name] += row[name]
    groups = []
    for name in order:
        if name in totals:
            total = totals[name]
            stdev = sample_stdev(total["hands"], total["bb"], total["squares"])
            groups.append(
                {
                    "key": name,
                    "hands": total["hands"],
                    "net_bb": round(total["bb"], 2),
                    "bb_stdev": None if stdev is None else round(stdev, 2),
                    "ev_net_bb": round(total["ev"], 2),
                }
            )
    return groups
