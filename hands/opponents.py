"""Opponents (FND-6, C1 and C2 of the feature ideas): everyone the user has played with, their statistics and a
label for their style, what their showdowns showed, and how the user fared against them.

`refresh` recomputes the opponents a batch of stored hands touched from all their HandPlayer rows, so a reparse
leaves them right where counting up as hands arrive would drift. Statistics are "did ÷ could", each with its sample,
as the hero's are [MIT 2].

The label follows the MIT course's four types [MIT 1], from how often a player puts money in (VPIP) and how
aggressive they are after the flop (bets and raises out of their bets, raises, calls and folds), or before it when
there's too little after (raises out of the hands they play). Its confidence comes from the Wilson intervals: high
when both ranges sit clear of the lines, medium when one does, low otherwise [JHU 4: label, and relabel when a
showdown says otherwise]. These lines are judgement calls, the same as My game's style quadrant.

Privacy: none of it is shown to anyone but the user who played the hands (feature ideas, section 7.6).
"""

from collections import defaultdict

from django.db.models import Count, F, Max, Min, Q, Sum

from hands import ranges
from hands.models import HandPlayer, Opponent
from hands.stats import POSITION_ORDER, proportion, sample_stdev
from tracker.parsing.facts import POSTFLOP_ACTIONS, STATS

LOOSE_VPIP = 25  # VPIP from which a player is loose, in percent
AGGRESSIVE = 40  # aggression after the flop from which a player is aggressive, in percent
RAISING = 0.5  # before the flop, raising at least this share of the hands they play
MIN_HANDS = 20  # fewer, and there's no label
MIN_POSTFLOP = 10  # moves after the flop for its aggression to count
COUNTED = [f"{stat}_{part}" for stat in STATS for part in ("could", "did")] + [
    f"postflop_{action}" for action in POSTFLOP_ACTIONS
]
# The ledger's pots, by their size in big blinds [MIT 2: PokerTracker's hero-versus-villain report].
POT_SIZES = (("small", 0, 10), ("medium", 10, 30), ("big", 30, 100), ("huge", 100, None))
WRITE_BATCH = 500


def refresh(user_id, keys):
    """Recomputes the user's opponents `keys`, (site, name) pairs, from every hand they were dealt into."""
    by_site = defaultdict(set)
    for site, name in keys:
        by_site[site].add(name)
    for site, names in by_site.items():
        names = list(names)
        for start in range(0, len(names), WRITE_BATCH):
            _refresh(user_id, site, names[start : start + WRITE_BATCH])


def _refresh(user_id, site, names):
    rows = HandPlayer.objects.filter(user_id=user_id, is_hero=False, hand__site=site, name__in=names)
    totals = rows.values("name").annotate(
        total_hands=Count("id"),
        first=Min("hand__played_at"),
        last=Max("hand__played_at"),
        total_net_bb=Sum("net_bb", default=0.0),
        total_invested_bb=Sum("invested_bb", default=0.0),
        **{f"total_{column}": Sum(column, default=0) for column in COUNTED},
    )
    # The hands both put money in by choice, or both saw the flop: one join to the hero's row, in one filter() so
    # every condition and the sum are on that same row.
    both = Q(vpip_did__gt=0, hand__seats__vpip_did__gt=0) | Q(saw_flop_did__gt=0, hand__seats__saw_flop_did__gt=0)
    shared = {
        row["name"]: row
        for row in HandPlayer.objects.filter(
            Q(user_id=user_id, is_hero=False, hand__site=site, name__in=names, hand__seats__is_hero=True) & both
        )
        .values("name")
        .annotate(shared=Count("id"), hero_net=Sum("hand__seats__net_bb", default=0.0))
        .order_by()
    }
    existing = {o.name: o for o in Opponent.objects.filter(user_id=user_id, site=site, name__in=names)}
    found = set()
    for row in totals.order_by():
        name = row["name"]
        found.add(name)
        counters = {
            column.removeprefix("total_"): value for column, value in row.items() if column.startswith("total_")
        }
        opponent = existing.get(name) or Opponent(user_id=user_id, site=site, name=name)
        opponent.hands = counters.pop("hands")
        opponent.first_seen, opponent.last_seen = row["first"], row["last"]
        opponent.counters = counters
        stats = core_stats(counters)
        opponent.vpip, opponent.pfr, opponent.aggression = (stats[key]["pct"] for key in ("vpip", "pfr", "aggression"))
        opponent.label, opponent.confidence = label(opponent.hands, stats)
        ledger = shared.get(name, {})
        opponent.shared_hands = ledger.get("shared", 0)
        opponent.hero_net_bb = round(ledger.get("hero_net", 0.0), 2)
        existing[name] = opponent
    fields = ("hands", "first_seen", "last_seen", "counters", "vpip", "pfr", "aggression", "label", "confidence")
    fields += ("shared_hands", "hero_net_bb")
    Opponent.objects.bulk_update([existing[name] for name in found if existing[name].pk], fields)
    Opponent.objects.bulk_create([existing[name] for name in found if not existing[name].pk])
    # A player whose every hand has gone, as a reparse can find, is no opponent any more.
    Opponent.objects.filter(user_id=user_id, site=site, name__in=set(names) - found).delete()


def core_stats(counters):
    """VPIP, PFR and the aggression frequency after the flop, from summed counters, as proportions."""
    aggressive = counters.get("postflop_bets", 0) + counters.get("postflop_raises", 0)
    passive = counters.get("postflop_calls", 0) + counters.get("postflop_folds", 0)
    return {
        "vpip": proportion(counters.get("vpip_did", 0), counters.get("vpip_could", 0)),
        "pfr": proportion(counters.get("pfr_did", 0), counters.get("pfr_could", 0)),
        "aggression": proportion(aggressive, aggressive + passive),
    }


def label(hands, stats):
    """A player's type and how sure it is, from their VPIP and aggression; ("", "") with too few hands to say."""
    vpip, aggression, pfr = stats["vpip"], stats["aggression"], stats["pfr"]
    if hands < MIN_HANDS or vpip["could"] < MIN_HANDS:
        return "", ""
    loose = vpip["pct"] >= LOOSE_VPIP
    sure_loose = vpip["ci_low"] >= LOOSE_VPIP if loose else vpip["ci_high"] < LOOSE_VPIP
    if aggression["could"] >= MIN_POSTFLOP:
        aggressive = aggression["pct"] >= AGGRESSIVE
        sure_aggressive = aggression["ci_low"] >= AGGRESSIVE if aggressive else aggression["ci_high"] < AGGRESSIVE
    else:  # too few moves after the flop: how much of what they play they raise
        aggressive = vpip["did"] > 0 and pfr["did"] >= RAISING * vpip["did"]
        sure_aggressive = False
    kind = ("lag" if loose else "tag") if aggressive else ("station" if loose else "rock")
    sure = sure_loose + sure_aggressive
    return kind, ("low", "medium", "high")[sure]


def effective_label(opponent):
    """The label that counts: the user's own, else the automatic one."""
    return opponent.manual_label or opponent.label


def positions(opponent):
    """The player's VPIP and PFR in each position, in the order they act, with their hands there."""
    rows = (
        HandPlayer.objects.filter(user=opponent.user, is_hero=False, hand__site=opponent.site, name=opponent.name)
        .values("position")
        .annotate(
            hands=Count("id"),
            vpip_could=Sum("vpip_could"),
            vpip_did=Sum("vpip_did"),
            pfr_could=Sum("pfr_could"),
            pfr_did=Sum("pfr_did"),
        )
        .order_by()
    )
    rank = {position: i for i, position in enumerate(POSITION_ORDER)}
    return [
        {
            "position": row["position"],
            "hands": row["hands"],
            "vpip": proportion(row["vpip_did"], row["vpip_could"]),
            "pfr": proportion(row["pfr_did"], row["pfr_could"]),
        }
        for row in sorted(rows, key=lambda row: (rank.get(row["position"], len(rank)), row["position"]))
    ]


def preflop_line(row):
    """What a player did before the flop, in a few words: "3-bet", "raised first in", "called a raise", ..."""
    if row.four_bet_did:
        return "4-bet"
    if row.three_bet_did:
        return "3-bet"
    if row.pfr_did:
        return "raised first in" if row.rfi_did else "raised"
    if row.first_action == "call":
        return "limped" if row.situation in ("unopened", "limped") else "called a raise"
    if row.first_action == "check":
        return "checked"
    return "folded" if row.first_action == "fold" else "posted"


SHOWDOWN_FIELDS = ("cards", "position", "situation", "first_action", "net_bb", "extra", "pfr_did", "rfi_did")
SHOWDOWN_FIELDS += ("three_bet_did", "four_bet_did", "hand__id", "hand__played_at", "hand__replay")
# How much each preflop line puts into a hand, for the surprise of what was shown with it.
_LINE_WEIGHT = {"4-bet": 4, "3-bet": 3, "raised first in": 2, "raised": 2, "called a raise": 1.5, "limped": 1}


def showdowns(opponent, limit=100):
    """The hands in which the player's cards were shown, the most surprising first: a strong preflop line with a
    weak starting hand ("3-bet with 7-5 offsuit") [JHU 4: work the hand backwards]. Each has the hand's id, when,
    their position, preflop line, cards and made hand, the board, their net and the surprise."""
    rows = (
        HandPlayer.objects.filter(user=opponent.user, is_hero=False, hand__site=opponent.site, name=opponent.name)
        .exclude(cards=[])
        .select_related("hand")
        .only(*SHOWDOWN_FIELDS)
        .order_by("-hand__played_at")[: limit * 4]
    )
    found = []
    for row in rows:
        line = preflop_line(row)
        combo = ranges.combo_of(row.cards)
        weakness = ranges.percentile(combo) if combo else 0.0
        board = row.hand.replay.get("board", [])
        shown = next(
            (
                event.get("description")
                for event in row.hand.replay.get("events", [])
                if event["type"] == "show" and event.get("player") == opponent.name
            ),
            None,
        )
        found.append(
            {
                "hand": row.hand.id,
                "played_at": row.hand.played_at,
                "position": row.position,
                "line": line,
                "cards": row.cards,
                "combo": combo,
                "shown": shown,
                "board": board,
                "net_bb": round(row.net_bb, 2),
                "surprise": round(_LINE_WEIGHT.get(line, 0) * weakness, 3),
                "actions": (row.extra or {}).get("actions", {}),
            }
        )
    found.sort(key=lambda showdown: (-showdown["surprise"], -showdown["played_at"].timestamp()))
    return found[:limit]


def pot_size(pot_bb):
    return next(name for name, low, high in POT_SIZES if pot_bb >= low and (high is None or pot_bb < high))


def ledger(opponent, biggest=3):
    """The hero against this player (C2): the hands both put money in by choice or both saw the flop, the hero's
    net in them by pot size, and the biggest pots the hero won and lost among them. The net is the hero's whole
    result in each hand, so in a pot of three or more it isn't all from this player."""
    both = Q(vpip_did__gt=0, hand__seats__vpip_did__gt=0) | Q(saw_flop_did__gt=0, hand__seats__saw_flop_did__gt=0)
    hero_rows = HandPlayer.objects.filter(
        Q(user=opponent.user, is_hero=True, hand__site=opponent.site, hand__seats__name=opponent.name) & both
    ).annotate(pot_bb=F("hand__total_pot") * 1.0 / F("hand__big_blind"))
    buckets = defaultdict(lambda: {"hands": 0, "net_bb": 0.0, "squares": 0.0})
    hands = []
    for row in hero_rows.values("hand_id", "net_bb", "pot_bb", "hand__played_at"):
        bucket = buckets[pot_size(row["pot_bb"] or 0)]
        bucket["hands"] += 1
        bucket["net_bb"] += row["net_bb"]
        bucket["squares"] += row["net_bb"] ** 2
        hands.append(row)
    by_net = sorted(hands, key=lambda row: row["net_bb"])

    def brief(row):
        net, pot = round(row["net_bb"], 2), round(row["pot_bb"] or 0, 1)
        return {"hand": row["hand_id"], "played_at": row["hand__played_at"], "net_bb": net, "pot_bb": pot}

    return {
        "hands": len(hands),
        "net_bb": round(sum(row["net_bb"] for row in hands), 2),
        "pots": [_pot_row(name, buckets[name]) for name, _, _ in POT_SIZES if name in buckets],
        "biggest_won": [brief(row) for row in reversed(by_net[-biggest:]) if row["net_bb"] > 0],
        "biggest_lost": [brief(row) for row in by_net[:biggest] if row["net_bb"] < 0],
    }


def _pot_row(size, bucket):
    stdev = sample_stdev(bucket["hands"], bucket["net_bb"], bucket["squares"])
    return {
        "size": size,
        "hands": bucket["hands"],
        "net_bb": round(bucket["net_bb"], 2),
        "bb_stdev": None if stdev is None else round(stdev, 2),
    }


def hands_with(opponent):
    """The user's hands the player was dealt into, as a Q on Hand."""
    return Q(pk__in=HandPlayer.objects.filter(user=opponent.user, name=opponent.name, is_hero=False).values("hand_id"))


# The opponents list's orders: most hands together, the hero's best or worst net against them, the latest seen.
OPPONENT_SORTS = {
    "hands": ("-hands", "name"),
    "best": ("-hero_net_bb", "name"),
    "worst": ("hero_net_bb", "name"),
    "recent": ("-last_seen", "name"),
}
