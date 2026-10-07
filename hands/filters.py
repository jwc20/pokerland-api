"""What the web app narrows a user's hands to: a tag, or a day in their time zone."""

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
