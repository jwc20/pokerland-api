"""Leak checks (B3 and B5 of the feature ideas): how often the hero broke a rule of thumb from the lectures.

A check is a pair of conditions on the hero's HandPlayer rows: the chances to keep its rule, and the times the rule
was broken. Counted like a statistic, did ÷ could, it gets a Wilson range and a month-by-month trend, and the game
history can list the hands behind it (`leak_hands`). One check, hands per orbit, is a rate instead.

The checks come in two groups: before the flop, B3's discipline checks (two of them B5's detectors 7 and 8), and
after it, B5's leak alerts 1, 3, 5 and 9. The user can mark a check reviewed (LeakReview), and its hands from
before then stop counting as new.

The thresholds are the user's coach presets: the course values in PRESETS unless they set their own. They are
presets, not truths: the lecturers disagree on some of them (the feature ideas, section 3).
"""

from django.db.models import Avg, Count, Exists, ExpressionWrapper, F, FloatField, OuterRef, Q, Sum, Value
from django.db.models.functions import Cast, TruncMonth

from hands.models import CoachPresets, HandBet, HandPlayer, LeakReview
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
    "bluff_opponents": {
        "default": 2.0,
        "min": 1.0,
        "max": 5.0,
        "label": "A bluff into this many opponents or more is one too many",
        "source": "JHU 5",
    },
    "cbet_opponents": {
        "default": 3.0,
        "min": 2.0,
        "max": 6.0,
        "label": "A c-bet into this many opponents or more is one too many",
        "source": "JHU 5",
    },
    "big_pot_bb": {
        "default": 40.0,
        "min": 10.0,
        "max": 200.0,
        "label": "A big pot: this many big blinds or more put in",
        "source": "MIT 5; JHU 4",
    },
    "deep_bb": {
        "default": 100.0,
        "min": 40.0,
        "max": 400.0,
        "label": "Deep stacks: an effective stack of this many big blinds or more",
        "source": "MIT 5; JHU 5",
    },
}

PREMIUMS = ("AA", "KK", "QQ", "AKs", "AKo")
LIMPED = ("unopened", "limped")  # a first call in these is a limp, not a call of a raise
LEAK_GROUPS = ("preflop", "postflop")
POSTFLOP = ("flop", "turn", "river")
# One pair, weaker than top pair: what a big pot shouldn't be played with at deep stacks [MIT 5; JHU 4; JHU 5].
SMALL_PAIRS = ("second_pair", "bottom_pair", "pocket_pair", "underpair")


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
    # B5's leak alerts after the flop.
    # 1. Don't fold a set, or two pair using both cards, on a dry, unpaired board [JHU 8].
    "folded_strong": lambda p: {"chances": Q(strong_fold_could__gt=0), "broken": Q(strong_fold_did__gt=0)},
    # 3. Thin value: checking the river back in position, then winning the showdown, left value unasked [JHU 9].
    "missed_thin_value": lambda p: {"chances": Q(thin_value_could__gt=0), "broken": Q(thin_value_did__gt=0)},
    # 5. Don't bluff into two or more opponents, or c-bet into three or more [JHU 5]. The chances are the hands with
    # a bluff (a bet or raise with nothing) or a c-bet after the flop.
    "multiway_bluff": lambda p: {
        "chances": _hero_bets(Q(strength="nothing") | Q(cbet=True)),
        "broken": _hero_bets(
            Q(strength="nothing", opponents__gte=p["bluff_opponents"])
            | Q(cbet=True, opponents__gte=p["cbet_opponents"])
        ),
    },
    # 9. Don't play a big pot with a small hand at deep stacks: 40 BB or more in with one pair weaker than top pair
    # [MIT 5; JHU 4; JHU 5]. Hold'em only, since Omaha's pairs aren't named.
    "big_pot_small_hand": lambda p: {
        "chances": Q(invested_bb__gte=p["big_pot_bb"], hand__effective_bb__gte=p["deep_bb"])
        & ~Q(hand__hero_combo=""),
        "broken": Q(hand__facts__hero__final__in=SMALL_PAIRS),
    },
}
# Play one or two hands an orbit [JHU 3; JHU 4]: a rate, not a rule kept or broken in a hand.
ORBIT = "hands_per_orbit"
LEAK_KEYS = (*CHECKS, ORBIT)
AFTER_THE_FLOP = ("folded_strong", "missed_thin_value", "multiway_bluff", "big_pot_small_hand")
GROUP_OF = {key: "postflop" if key in AFTER_THE_FLOP else "preflop" for key in LEAK_KEYS}


def _hero_bets(q):
    """The hero's rows with a bet or raise after the flop that meets `q`."""
    bets = HandBet.objects.filter(q, hand=OuterRef("hand"), is_hero=True, street__in=POSTFLOP)
    return Q(Exists(bets))


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


def leaks(user, hands, presets, tz, group=None):
    """Every check over the hero's rows in `hands`, or a group's: its count, its range, its trend by month in `tz`,
    and when the user last marked it reviewed, with the hands that broke it since."""
    rows = HandPlayer.objects.filter(is_hero=True, hand__in=hands)
    reviewed = dict(LeakReview.objects.filter(user=user).values_list("key", "reviewed"))
    keys = [key for key in LEAK_KEYS if group is None or GROUP_OF[key] == group]
    return [
        _orbit_check(rows, tz) if key == ORBIT else _share_check(key, rows, presets, tz, reviewed.get(key))
        for key in keys
    ]


def _share_check(key, rows, presets, tz, reviewed=None):
    check = _conditions(key, presets)
    chances = rows.filter(check["chances"])
    counts = {
        "could": Count("id"),
        "did": Count("id", filter=check["broken"]),
        "net_broken_bb": Sum("net_bb", filter=check["broken"], default=0.0),
        "net_kept_bb": Sum("net_bb", filter=~check["broken"], default=0.0),
    }
    if reviewed:
        counts["new"] = Count("id", filter=check["broken"] & Q(hand__played_at__gt=reviewed))
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
        "reviewed": reviewed,
        "new": totals["new"] if reviewed else totals["did"],
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
        "reviewed": None,
        "new": None,
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


def mark_reviewed(user, key, when):
    """Marks check `key` reviewed at `when`: its hands from before then are no longer new."""
    review, _ = LeakReview.objects.update_or_create(user=user, key=key, defaults={"reviewed": when})
    return review
