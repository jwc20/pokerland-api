"""What the web app narrows a user's hands to: tags, days in their time zone, decisions, results and notes."""

import datetime
import functools
import zoneinfo

from django.db.models import Case, CharField, Q, Value, When

# The hands the user was dealt into. One without a hero (a hand they sat out,
# say) is neither won nor lost, so the dashboard leaves it out of its counts.
PLAYED = ~Q(hero="")

# Every hand has exactly one format.
FORMATS = {
    "cash": Q(tournament_id="", play_money=False),
    "play_money": Q(tournament_id="", play_money=True),
    "tournament": ~Q(tournament_id=""),
}
FORMAT = Case(*(When(condition, then=Value(name)) for name, condition in FORMATS.items()), output_field=CharField())

# What a tag groups hands by. Its key is "<group>:<value>", or "all".
TAG_GROUPS = ["all", "position", "game", "stakes", "format"]

UTC = zoneinfo.ZoneInfo("UTC")

RESULTS = {"won": Q(hero_net__gt=0), "lost": Q(hero_net__lt=0), "even": Q(hero_net=0)}
HAND_RESULTS = tuple(RESULTS)

# The game history's orders. By result goes in big blinds (the `net_bb` annotation), so stakes compare;
# the id breaks ties, so a cursor never skips or repeats a hand.
SORT_ORDERS = {
    "newest": ("-played_at", "-id"),
    "oldest": ("played_at", "id"),
    "biggest_win": ("-net_bb", "-id"),
    "biggest_loss": ("net_bb", "id"),
}
HAND_SORTS = tuple(SORT_ORDERS)


def tag_key(group, value):
    return group if group == "all" else f"{group}:{value}"


def stakes_value(currency, small_blind, big_blind):
    """A stakes tag's value: "USD:5:10" for $0.05/$0.10, ":100:200" for chips."""
    return f"{currency}:{small_blind}:{big_blind}"


def tag_filter(key):
    """The hands the tag `key` counts, as a Q; ValueError if `key` is not a tag's key."""
    group, _, value = key.partition(":")
    if key == "all":
        return Q()
    if group == "position" and value:
        return Q(hero_position=value)
    if group == "game" and value:
        return Q(game=value)
    if group == "format" and value in FORMATS:
        return FORMATS[value]
    if group == "stakes":
        currency, small_blind, big_blind = value.split(":")
        # Cash games only: tournament blinds go up every level.
        return Q(tournament_id="", currency=currency, small_blind=int(small_blind), big_blind=int(big_blind))
    raise ValueError(f"Not a tag: {key!r}")


@functools.cache
def _zone_names():
    return frozenset(zoneinfo.available_timezones())


def zone(name):
    """The IANA time zone `name`, e.g. "Europe/London"; ValueError if there is none.

    The name is looked up in the time zone database's list rather than opened as
    a file, which would take "utc" on a case-insensitive file system and raise
    OSError for a name too long to be a path.
    """
    if name not in _zone_names():
        raise ValueError(f"Not a time zone: {name!r}")
    return zoneinfo.ZoneInfo(name)


def day_bounds(day, tz):
    """When `day` begins in `tz` and when the next one does: 23 or 25 hours apart when the clocks change."""
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)
    end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
    return start, end


def stat_filter(stat, did=None):
    """The hands that gave the hero a chance at `stat`, as a Q; with `did`, those where they took it, or not.

    `stat` is one of tracker.parsing.facts.STATS, or "aggression": a move after
    the flop, taken when it was a bet or a raise. Every condition is on the
    hero's own HandPlayer row, so the Q must go into a single filter() call.
    """
    seat = {"seats__is_hero": True}
    if stat == "aggression":
        aggressive = Q(seats__postflop_bets__gt=0) | Q(seats__postflop_raises__gt=0)
        chance = aggressive | Q(seats__postflop_calls__gt=0) | Q(seats__postflop_folds__gt=0)
        took, passed = aggressive, Q(seats__postflop_bets=0, seats__postflop_raises=0)
    else:
        chance = Q(**{f"seats__{stat}_could__gt": 0})
        took, passed = Q(**{f"seats__{stat}_did__gt": 0}), Q(**{f"seats__{stat}_did": 0})
    if did is None:
        return Q(**seat) & chance
    return Q(**seat) & chance & (took if did else passed)


def narrow(hands, filters):
    """`hands` narrowed by the validated filters of hands.serializers.HandFilterSerializer and its subclasses.

    A spot, a spec, an opponent or a tournament comes as a Q the serializer built (`where`), since building it
    takes the user's own spots, opponents and tournaments.
    """
    tz = filters.get("tz", UTC)
    for condition in filters.get("where", []):
        hands = hands.filter(condition)
    for key in filters.get("tag", []):
        hands = hands.filter(tag_filter(key))
    if "since" in filters:
        hands = hands.filter(played_at__gte=day_bounds(filters["since"], tz)[0])
    if "until" in filters:
        hands = hands.filter(played_at__lt=day_bounds(filters["until"], tz)[1])
    if "date" in filters:
        start, end = day_bounds(filters["date"], tz)
        hands = hands.filter(played_at__gte=start, played_at__lt=end)
    if "stat" in filters:
        hands = hands.filter(stat_filter(filters["stat"], filters.get("did")))
    if "result" in filters:
        hands = hands.filter(RESULTS[filters["result"]])
    # A hand has one review state and each tag once, so neither join repeats a hand.
    if "review" in filters:
        hands = hands.filter(notes__kind="review", notes__value=filters["review"])
    if "note_tag" in filters:
        hands = hands.filter(notes__kind="tag", notes__value=filters["note_tag"])
    if "session" in filters:
        hands = hands.filter(session_id=filters["session"])
    return hands
