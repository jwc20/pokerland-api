"""Leak checks (B3 of the feature ideas, and B5 to come): how often the hero broke a rule of thumb from the lectures.

A check is a pair of conditions on the hero's HandPlayer rows: the chances to keep its rule, and the times the rule
was broken. Counted like a statistic, did ÷ could, it gets a Wilson range and a month-by-month trend, and the game
history can list the hands behind it (`leak_hands`). One check, hands per orbit, is a rate instead.

The thresholds are the user's coach presets: the course values in PRESETS unless they set their own. They are
presets, not truths: the lecturers disagree on some of them (the feature ideas, section 3).
"""

from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Q, Sum, Value
from django.db.models.functions import Cast, TruncMonth

from hands.models import CoachPresets, HandPlayer
from hands.stats import proportion

# Each preset's course value, the range it may be set in, what it is, and where it comes from.
PRESETS = {
    "open_bb": {
        "default": 3.0,
        "min": 2.0,
        "max": 6.0,
        "label": "Open-raise in cash games to, in big blinds",
        "source": "JHU 3; MIT 5",
    },
    "limper_bb": {
        "default": 1.0,
        "min": 0.0,
        "max": 3.0,
        "label": "Plus, for each limper, in big blinds",
        "source": "JHU 3; MIT 5",
    },
    "tournament_open_bb": {
        "default": 2.5,
        "min": 2.0,
        "max": 6.0,
        "label": "Open-raise in tournaments to, in big blinds",
        "source": "JHU 3",
    },
    "three_bet_x": {
        "default": 3.0,
        "min": 2.0,
        "max": 6.0,
        "label": "3-bet to this many times the raise, plus one more for each caller",
        "source": "JHU 4",
    },
    "size_slack": {
        "default": 0.5,
        "min": 0.0,
        "max": 2.0,
        "label": "A size this close to the standard keeps the rule: big blinds, or raises for a 3-bet",
        "source": "",
    },
    "short_stack_bb": {
        "default": 10.0,
        "min": 5.0,
        "max": 25.0,
        "label": "At or below this effective stack, in big blinds, move in instead of raising small",
        "source": "JHU 6",
    },
    "buy_in_bb": {
        "default": 100.0,
        "min": 20.0,
        "max": 250.0,
        "label": "Start every cash-game hand with at least this many big blinds",
        "source": "JHU 3",
    },
    "orbit_min": {
        "default": 1.0,
        "min": 0.0,
        "max": 9.0,
        "label": "Hands to play an orbit, at least",
        "source": "JHU 3; JHU 4",
    },
    "orbit_max": {
        "default": 2.0,
        "min": 0.5,
        "max": 9.0,
        "label": "Hands to play an orbit, at most",
        "source": "JHU 3; JHU 4",
    },
}

PREMIUMS = ("AA", "KK", "QQ", "AKs", "AKo")
LIMPED = ("unopened", "limped")  # a first call in these is a limp, not a call of a raise
LEAK_GROUPS = ("preflop",)


def presets_of(user):
    """The user's presets: their own values where they set one, the course values elsewhere."""
    row = CoachPresets.objects.filter(user=user).first()
    own = row.values if row else {}
    return {name: float(own.get(name, preset["default"])) for name, preset in PRESETS.items()}


def _standard(base, each, count):
    """A standard size: `base`, plus `each` for every one of the row's `count` (limpers, callers)."""
    return ExpressionWrapper(Value(base) + Value(each) * F(count), output_field=FloatField())


def _below(column, standard, slack):
    return Q(**{f"{column}__lt": standard - Value(slack)})


def _above(column, standard, slack):
    return Q(**{f"{column}__gt": standard + Value(slack)})


def _open_sizes(p):
    """Open to 3 BB plus 1 BB for each limper; in tournaments, 2 to 2.5 BB [JHU 3; MIT 5]. A move-in has no size."""
    cash, tournament = Q(hand__tournament_id=""), ~Q(hand__tournament_id="")
    standards = (
        (cash, _standard(p["open_bb"], p["limper_bb"], "open_limpers")),
        (tournament, _standard(p["tournament_open_bb"], p["limper_bb"], "open_limpers")),
    )
    below = Q()
    above = Q()
    for kind, standard in standards:
        below |= kind & _below("open_bb", standard, p["size_slack"])
        above |= kind & _above("open_bb", standard, p["size_slack"])
    return {"chances": Q(open_bb__isnull=False, first_raise_all_in=False), "below": below, "above": above}


def _three_bet_sizes(p):
    """3-bet to three times the raise, and more over callers [JHU 4]. A move-in has no size."""
    standard = _standard(p["three_bet_x"], 1.0, "three_bet_callers")
    return {
        "chances": Q(three_bet_x__isnull=False, first_raise_all_in=False),
        "below": _below("three_bet_x", standard, p["size_slack"]),
        "above": _above("three_bet_x", standard, p["size_slack"]),
    }


# Each check's chances and the times its rule was broken, from the presets. Sizes broken either way also count
# the small (`below`) and the big (`above`) apart, and `average` names the column whose mean they show.
CHECKS = {
    # Never open-limp: raise or fold when the pot is folded to you [JHU 3; JHU 4].
    "open_limp": lambda p: {"chances": Q(rfi_could__gt=0), "broken": Q(first_action="call")},
    "open_size": lambda p: {**_open_sizes(p), "average": "open_bb"},
    "three_bet_size": lambda p: {**_three_bet_sizes(p), "average": "three_bet_x"},
    # With 10 BB or less, never raise small: move in [JHU 6].
    "short_stack_raise": lambda p: {
        "chances": Q(hand__effective_bb__lte=p["short_stack_bb"], first_raise_all_in__isnull=False),
        "broken": Q(first_raise_all_in=False),
    },
    # Queens or better and ace-king are raised, not limped into a pot four or more see the flop [JHU 4].
    "premium_limp": lambda p: {
        "chances": Q(hand__hero_combo__in=PREMIUMS),
        "broken": Q(first_action="call", situation__in=LIMPED, pfr_did=0, hand__facts__players_at_flop__gte=4),
    },
    # Buy in for the full 100 BB, and top up [JHU 3].
    "short_buy_in": lambda p: {"chances": Q(hand__tournament_id=""), "broken": Q(stack_bb__lt=p["buy_in_bb"])},
}
# Play one or two hands an orbit [JHU 3; JHU 4]: a rate, not a rule kept or broken in a hand.
ORBIT = "hands_per_orbit"
LEAK_KEYS = (*CHECKS, ORBIT)
GROUP_OF = dict.fromkeys(LEAK_KEYS, "preflop")


def _conditions(key, presets):
    check = CHECKS[key](presets)
    if "broken" not in check:
        check["broken"] = check["below"] | check["above"]
    return check


def leak_hands(user, key, presets):
    """The hands in which the hero broke check `key`'s rule, as a Q on Hand."""
    check = _conditions(key, presets)
    rows = HandPlayer.objects.filter(check["chances"] & check["broken"], user=user, is_hero=True)
    return Q(pk__in=rows.values("hand_id"))


def leaks(user, hands, presets, tz):
    """Every check over the hero's rows in `hands`: its count, its range, its trend by month in `tz`."""
    rows = HandPlayer.objects.filter(is_hero=True, hand__in=hands)
    results = [_share_check(key, rows, presets, tz) for key in CHECKS]
    results.append(_orbit_check(rows, tz))
    return results


def _share_check(key, rows, presets, tz):
    check = _conditions(key, presets)
    chances = rows.filter(check["chances"])
    counts = {
        "could": Count("id"),
        "did": Count("id", filter=check["broken"]),
        "net_broken_bb": Sum("net_bb", filter=check["broken"], default=0.0),
        "net_kept_bb": Sum("net_bb", filter=~check["broken"], default=0.0),
    }
    if "below" in check:
        counts.update(below=Count("id", filter=check["below"]), above=Count("id", filter=check["above"]))
    if "average" in check:
        counts["average"] = Avg(check["average"])
    totals = chances.aggregate(**counts)
    months = (
        chances.annotate(month=TruncMonth("hand__played_at", tzinfo=tz))
        .values("month")
        .annotate(could=Count("id"), did=Count("id", filter=check["broken"]))
        .order_by("month")
    )
    return {
        "key": key,
        "group": GROUP_OF[key],
        "share": proportion(totals["did"], totals["could"]),
        "rate": None,
        "average": None if totals.get("average") is None else round(totals["average"], 2),
        "below": totals.get("below"),
        "above": totals.get("above"),
        "net_broken_bb": round(totals["net_broken_bb"], 2),
        "net_kept_bb": round(totals["net_kept_bb"], 2),
        "months": [
            {"month": row["month"].strftime("%Y-%m"), "did": row["did"], "could": row["could"], "rate": None}
            for row in months
        ],
    }


def _orbit_check(rows, tz):
    """Hands played, VPIP, per orbit: per as many hands as there were players dealt in."""
    played = rows.filter(vpip_could__gt=0, hand__players_dealt__gt=0)
    sums = {"played": Sum("vpip_did", default=0), "orbits": Sum(1.0 / Cast("hand__players_dealt", FloatField()))}
    totals = played.aggregate(**sums)
    months = (
        played.annotate(month=TruncMonth("hand__played_at", tzinfo=tz)).values("month").annotate(**sums).order_by()
    )

    def rate(row):
        return round(row["played"] / row["orbits"], 2) if row["orbits"] else None

    return {
        "key": ORBIT,
        "group": GROUP_OF[ORBIT],
        "share": None,
        "rate": rate(totals),
        "average": None,
        "below": None,
        "above": None,
        "net_broken_bb": None,
        "net_kept_bb": None,
        "months": [
            {"month": row["month"].strftime("%Y-%m"), "did": row["played"], "could": None, "rate": rate(row)}
            for row in sorted(months, key=lambda row: row["month"])
        ],
    }


def preset_rows(user):
    """Every preset with the user's value, its course value, its range, and what it means."""
    values = presets_of(user)
    return [{"key": name, "value": values[name], **preset} for name, preset in PRESETS.items()]


def save_presets(user, changes):
    """Sets the presets in `changes`; a None puts that one back to the course value."""
    row, _ = CoachPresets.objects.get_or_create(user=user)
    for name, value in changes.items():
        if value is None:
            row.values.pop(name, None)
        else:
            row.values[name] = value
    row.save()
