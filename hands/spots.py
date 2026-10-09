"""Spots (FND-3 of the feature ideas): filters as rich as PokerTracker's [MIT 2], kept as JSON and turned into a Q.

A spec is a condition, or a group of specs:

    {"all": [spec, ...]}                          every one holds
    {"any": [spec, ...]}                          at least one does
    {"not": spec}                                 it doesn't
    {"field": "position", "value": ["BTN", "CO"]}  a condition

FIELDS lists the conditions and what each takes: `value` (one or a list of choices, a number, true or false, or
text), `min` and `max`, `street`, and a few of their own. `validate` checks a spec and returns it tidied, or raises
SpotError naming what is wrong and where; `spot_filter` turns a valid spec into a Q on Hand.

Conditions on the hero's own row or on other rows (a bet, an opponent, a note) are subqueries tied to the hand, so a
`not` means what it says: a hand without such a row. Hole-card conditions are hold'em's (Omaha hands have no
combo), and street conditions go by what the hero saw: their made hand, draws, line and the board's texture on a
street they were dealt into.
"""

import datetime
import json

from django.db.models import Exists, F, OuterRef, Q

from hands import ranges
from hands.filters import FORMATS, RESULTS, day_bounds, tag_filter
from hands.leaks import CHECKS, leak_hands, presets_of
from hands.models import HandBet, HandNote, HandPlayer, Opponent, Tournament
from hands.notes import REVIEW_STATES
from tracker.parsing.facts import ALL_HAND_GROUPS, SIZING_FLAGS, STATS, TEXTURES

MAX_DEPTH = 5
MAX_CONDITIONS = 40
STREETS = ("preflop", "flop", "turn", "river")
POSTFLOP = STREETS[1:]
POSITIONS = ("UTG", "UTG+1", "UTG+2", "UTG+3", "UTG+4", "UTG+5", "LJ", "HJ", "CO", "BTN", "SB", "BB")
POT_TYPES = ("walk", "limped", "single_raised", "3bet", "4bet+")
SITUATIONS = ("unopened", "limped", "raised", "3bet", "4bet+")
FIRST_ACTIONS = ("fold", "check", "call", "raise")
MOVES = ("fold", "check", "call", "bet", "raise")
ROLES = ("raised", "called", "limped")
# What tracker.parsing.facts.made_hand calls a hand: hold'em's own pairs and trips, then PokerKit's categories.
MADE_HANDS = ("high_card", "overcards", "underpair", "pocket_pair", "bottom_pair", "second_pair", "top_pair")
MADE_HANDS += ("top_pair_top_kicker", "overpair", "one_pair", "two_pair", "trips", "set", "three_of_a_kind")
MADE_HANDS += ("straight", "flush", "full_house", "four_of_a_kind", "straight_flush")
DRAWS = ("nut_flush_draw", "flush_draw", "backdoor_flush_draw", "open_ended", "double_gutshot", "gutshot")
LABELS = ("tag", "lag", "rock", "station")


class SpotError(ValueError):
    """A spec that isn't valid; the message says what and where."""


def _choices(value, choices, path, many=True):
    values = value if isinstance(value, list) else [value]
    if not values or (not many and len(values) != 1):
        raise SpotError(f"{path}: give {'one or more' if many else 'one'} of {', '.join(choices)}.")
    for item in values:
        if item not in choices:
            raise SpotError(f"{path}: {item!r} is not one of {', '.join(choices)}.")
    return values if many else values[0]


def _number(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpotError(f"{path}: a number, please.")
    return value


def _texts(value, path, limit=200):
    values = value if isinstance(value, list) else [value]
    if not values or len(values) > limit or not all(isinstance(item, str) and item.strip() for item in values):
        raise SpotError(f"{path}: give one or more names.")
    return [item.strip() for item in values]


def _day(value, path):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise SpotError(f"{path}: a day, as YYYY-MM-DD.") from None


# Each field: the parameters it takes, with a function that checks one and returns it tidied.
class Choice:
    """A parameter that takes one of `options`, or with `many` a list of them; /api/spots/fields/ lists them."""

    def __init__(self, *options, many=True):
        self.options, self.many = options, many

    def __call__(self, value, path):
        return _choices(value, self.options, path, self.many)


def choice(*options, many=True):
    return Choice(*options, many=many)


def boolean(value, path):
    if not isinstance(value, bool):
        raise SpotError(f"{path}: true or false.")
    return value


def street_of(*options):
    return choice(*options, many=False)


def text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise SpotError(f"{path}: some text, please.")
    return value.strip()


def percent(value, path):
    value = _number(value, path)
    if not 0 < value <= 100:
        raise SpotError(f"{path}: a share from 0 to 100.")
    return value


def range_notation(value, path):
    value = text(value, path)
    try:
        ranges.parse(value)
    except ValueError as error:
        raise SpotError(f"{path}: {error}") from None
    return value


def hands_list(value, path):
    values = _texts(value, path, limit=169)
    for hand in values:
        if hand not in ranges.HANDS:
            raise SpotError(f"{path}: {hand!r} is not a starting hand such as AA, AKs or T9o.")
    return values


def tag_key(value, path):
    value = text(value, path)
    try:
        tag_filter(value)
    except ValueError:
        raise SpotError(f"{path}: {value!r} is not a tag.") from None
    return value


stat_name = Choice(*STATS, "aggression", many=False)
leak_key = Choice(*CHECKS, many=False)


RANGE = {"min": _number, "max": _number}
FIELDS = {
    # The game
    "tag": {"value": tag_key},
    "format": {"value": choice(*FORMATS)},
    "game": {"value": _texts},
    "stakes": {"value": _texts},
    "date": {"since": _day, "until": _day},
    "table_size": RANGE,
    "buy_in": RANGE,  # a tournament's whole buy-in, fee and bounty included, in cents or chips
    "m": RANGE,
    # The hand
    "players": RANGE,
    "pot_type": {"value": choice(*POT_TYPES)},
    "situation": {"value": choice(*SITUATIONS)},
    "first_action": {"value": choice(*FIRST_ACTIONS)},
    "position": {"value": choice(*POSITIONS)},
    "saw_flop": {"value": boolean},
    "showdown": {"value": boolean},
    "all_in": {"value": boolean},
    "result": {"value": choice(*RESULTS, many=False)},
    "pot_bb": RANGE,
    "effective_bb": RANGE,
    "net_bb": RANGE,
    # The hole cards
    "hands": {"value": hands_list},
    "range": {"value": range_notation},
    "top": {"value": percent},
    "hand_group": {"value": choice(*ALL_HAND_GROUPS)},
    # The streets
    "made": {"street": street_of(*POSTFLOP), "value": choice(*MADE_HANDS)},
    "draw": {"street": street_of("flop", "turn"), "value": choice(*DRAWS)},
    "texture": {"street": street_of(*POSTFLOP), "value": choice(*TEXTURES)},
    "line": {
        "street": street_of(*POSTFLOP),
        "role": choice(*ROLES, many=False),
        "ip": boolean,
        "first": choice("bet", "check", many=False),
        "faced": choice("fold", "call", "raise", many=False),
    },
    "action": {"street": street_of(*STREETS), "value": choice(*MOVES, many=False)},
    "bet_size": {"street": street_of(*STREETS), **RANGE},
    "faced_size": {"street": street_of(*STREETS), **RANGE},
    "sizing_flag": {"value": choice(*SIZING_FLAGS)},
    # The people
    "opponent": {"value": _texts},
    "opponent_label": {"value": choice(*LABELS)},
    # The study
    "stat": {"value": stat_name, "did": boolean},
    "leak": {"value": leak_key},
    "review": {"value": choice(*REVIEW_STATES, many=False)},
    "note_tag": {"value": text},
    "tournament": {"value": _texts},
}
# Parameters a field can do without; every other one it lists is required, and of min and max one will do.
OPTIONAL = {"did", "role", "ip", "first", "faced", "since", "until", "min", "max"}


def spot_fields():
    """Every condition, the parameters it takes, those it needs, and the choices of those that have a fixed set."""
    return [
        {
            "field": name,
            "params": list(params),
            "required": [param for param in params if param not in OPTIONAL],
            "choices": {param: list(check.options) for param, check in params.items() if isinstance(check, Choice)},
        }
        for name, params in FIELDS.items()
    ]


def validate(spec, path="spec", depth=0, count=None):
    """`spec` checked and tidied; SpotError if it isn't a valid spec."""
    count = count if count is not None else [0]
    if depth > MAX_DEPTH:
        raise SpotError(f"{path}: groups nested more than {MAX_DEPTH} deep.")
    if not isinstance(spec, dict):
        raise SpotError(f"{path}: a condition or a group, as an object.")
    groups = [key for key in ("all", "any", "not") if key in spec]
    if groups:
        if len(groups) > 1 or len(spec) > 1:
            raise SpotError(f"{path}: a group is one of all, any or not, and nothing else.")
        key = groups[0]
        if key == "not":
            return {"not": validate(spec["not"], f"{path}.not", depth + 1, count)}
        members = spec[key]
        if not isinstance(members, list):
            raise SpotError(f"{path}.{key}: a list of conditions.")
        return {key: [validate(member, f"{path}.{key}[{i}]", depth + 1, count) for i, member in enumerate(members)]}
    count[0] += 1
    if count[0] > MAX_CONDITIONS:
        raise SpotError(f"{path}: more than {MAX_CONDITIONS} conditions.")
    field = spec.get("field")
    if field not in FIELDS:
        raise SpotError(f"{path}.field: {field!r} is not a condition.")
    params = FIELDS[field]
    unknown = set(spec) - {"field", *params}
    if unknown:
        raise SpotError(f"{path}: {field} takes {', '.join(params)}, not {', '.join(sorted(unknown))}.")
    tidy = {"field": field}
    for name, check in params.items():
        if spec.get(name) is not None:
            tidy[name] = check(spec[name], f"{path}.{name}")
        elif name not in OPTIONAL:
            raise SpotError(f"{path}.{name}: {field} needs it.")
    if set(params) & {"min", "max"} and "min" not in tidy and "max" not in tidy:
        raise SpotError(f"{path}: give min, max or both.")
    if field == "date" and "since" not in tidy and "until" not in tidy:
        raise SpotError(f"{path}: give since, until or both.")
    return tidy


def parse(text_or_spec):
    """A spec from JSON text, or as given, validated."""
    spec = text_or_spec
    if isinstance(text_or_spec, str):
        try:
            spec = json.loads(text_or_spec)
        except json.JSONDecodeError:
            raise SpotError("spec: not JSON.") from None
    return validate(spec)


def spot_filter(spec, user, tz):
    """The hands a valid `spec` matches, as a Q on the user's Hand rows; days are counted in `tz`."""
    if "all" in spec:
        q = Q()
        for member in spec["all"]:
            q &= spot_filter(member, user, tz)
        return q
    if "any" in spec:
        if not spec["any"]:
            return Q()
        q = Q(pk__in=[])
        for member in spec["any"]:
            q |= spot_filter(member, user, tz)
        return q
    if "not" in spec:
        return ~spot_filter(spec["not"], user, tz)
    return BUILDERS[spec["field"]](spec, user, tz)


def _between(column, spec):
    q = Q()
    if "min" in spec:
        q &= Q(**{f"{column}__gte": spec["min"]})
    if "max" in spec:
        q &= Q(**{f"{column}__lte": spec["max"]})
    return q


def _hero(**conditions):
    """The hands whose hero row meets `conditions`."""
    return Q(Exists(HandPlayer.objects.filter(hand=OuterRef("pk"), is_hero=True, **conditions)))


def _hero_q(q):
    return Q(Exists(HandPlayer.objects.filter(q, hand=OuterRef("pk"), is_hero=True)))


def _combos(names):
    return Q(hero_combo__in=sorted(names))


def _stakes(value):
    q = Q(pk__in=[])
    for stakes in value:
        try:
            q |= tag_filter(f"stakes:{stakes}")
        except ValueError:
            continue  # stakes no hand has match no hand
    return q


def _date(spec, user, tz):
    q = Q()
    if "since" in spec:
        q &= Q(played_at__gte=day_bounds(datetime.date.fromisoformat(spec["since"]), tz)[0])
    if "until" in spec:
        q &= Q(played_at__lt=day_bounds(datetime.date.fromisoformat(spec["until"]), tz)[1])
    return q


def _buy_in(spec, user, tz):
    total = F("buy_in") + F("fee") + F("bounty")
    tournaments = Tournament.objects.filter(user=user).annotate(total=total).filter(_between("total", spec))
    return Q(tournament_id__in=tournaments.values("tournament_id"))


def _texture(spec, user, tz):
    return Q(**{f"facts__hero__lines__{spec['street']}__texture__in": spec["value"]})


def _draw(spec, user, tz):
    q = Q(pk__in=[])
    for draw in spec["value"]:  # a list of draws in JSON: quoted, so "flush_draw" isn't found in "nut_flush_draw"
        q |= Q(**{f"facts__hero__draws__{spec['street']}__icontains": f'"{draw}"'})
    return q


def _line(spec, user, tz):
    """The hero's line on a street; with nothing more than the street, that they played it."""
    street = spec["street"]
    keys = [key for key in ("role", "ip", "first", "faced") if key in spec]
    if not keys:
        return Q(facts__hero__lines__has_key=street)
    return Q(**{f"facts__hero__lines__{street}__{key}": spec[key] for key in keys})


def _bets(spec, **conditions):
    bets = HandBet.objects.filter(_between("size", spec), hand=OuterRef("pk"), street=spec["street"], **conditions)
    return Q(Exists(bets))


def _sizing_flag(spec, user, tz):
    q = Q(pk__in=[])
    for flag in spec["value"]:
        q |= Q(facts__hero__flags__icontains=f'"{flag}"')
    return q


def _opponent_label(spec, user, tz):
    labels = spec["value"]
    named = Opponent.objects.filter(Q(manual_label__in=labels) | Q(manual_label="", label__in=labels), user=user)
    others = HandPlayer.objects.filter(hand=OuterRef("pk"), is_hero=False, name__in=named.values("name"))
    return Q(Exists(others))


def _stat(spec, user, tz):
    stat, did = spec["value"], spec.get("did")
    if stat == "aggression":
        aggressive = Q(postflop_bets__gt=0) | Q(postflop_raises__gt=0)
        chance = aggressive | Q(postflop_calls__gt=0) | Q(postflop_folds__gt=0)
        took, passed = aggressive, Q(postflop_bets=0, postflop_raises=0)
    else:
        chance = Q(**{f"{stat}_could__gt": 0})
        took, passed = Q(**{f"{stat}_did__gt": 0}), Q(**{f"{stat}_did": 0})
    return _hero_q(chance if did is None else chance & (took if did else passed))


def _leak(spec, user, tz):
    return leak_hands(user, spec["value"], presets_of(user))


def _notes(**conditions):
    return Q(Exists(HandNote.objects.filter(hand=OuterRef("pk"), **conditions)))


def _hand_group(spec, user, tz):
    groups = set(spec["value"])
    return _combos(hand for hand in ranges.HANDS if ranges.group_of(hand) in groups)


BUILDERS = {
    "tag": lambda spec, user, tz: tag_filter(spec["value"]),
    "format": lambda spec, user, tz: _any_of(FORMATS[name] for name in spec["value"]),
    "game": lambda spec, user, tz: Q(game__in=spec["value"]),
    "stakes": lambda spec, user, tz: _stakes(spec["value"]),
    "date": _date,
    "table_size": lambda spec, user, tz: _between("replay__max_seats", spec),
    "buy_in": _buy_in,
    "m": lambda spec, user, tz: _between("hero_m", spec),
    "players": lambda spec, user, tz: _between("players_dealt", spec),
    "pot_type": lambda spec, user, tz: Q(pot_type__in=spec["value"]),
    "situation": lambda spec, user, tz: Q(hero_situation__in=spec["value"]),
    "first_action": lambda spec, user, tz: Q(hero_first_action__in=spec["value"]),
    "position": lambda spec, user, tz: Q(hero_position__in=spec["value"]),
    "saw_flop": lambda spec, user, tz: _hero(saw_flop_did=int(spec["value"])),
    "showdown": lambda spec, user, tz: _hero(went_to_showdown_did=int(spec["value"])),
    "all_in": lambda spec, user, tz: _hero_q(~Q(allin_street="") if spec["value"] else Q(allin_street="")),
    "result": lambda spec, user, tz: RESULTS[spec["value"]],
    "pot_bb": lambda spec, user, tz: _bb_between("total_pot", spec),
    "effective_bb": lambda spec, user, tz: _between("effective_bb", spec),
    "net_bb": lambda spec, user, tz: _bb_between("hero_net", spec),
    "hands": lambda spec, user, tz: _combos(spec["value"]),
    "range": lambda spec, user, tz: _combos(ranges.parse(spec["value"])),
    "top": lambda spec, user, tz: _combos(ranges.top(spec["value"])),
    "hand_group": _hand_group,
    "made": lambda spec, user, tz: Q(**{f"facts__hero__made__{spec['street']}__in": spec["value"]}),
    "draw": _draw,
    "texture": _texture,
    "line": _line,
    "action": lambda spec, user, tz: _hero(**{f"extra__actions__{spec['street']}__{spec['value']}s__gt": 0}),
    "bet_size": lambda spec, user, tz: _bets(spec, is_hero=True),
    "faced_size": lambda spec, user, tz: Q(Exists(_faced(spec))),
    "sizing_flag": _sizing_flag,
    "opponent": lambda spec, user, tz: Q(
        Exists(HandPlayer.objects.filter(hand=OuterRef("pk"), is_hero=False, name__in=spec["value"]))
    ),
    "opponent_label": _opponent_label,
    "stat": _stat,
    "leak": _leak,
    "review": lambda spec, user, tz: _notes(kind=HandNote.Kind.REVIEW, value=spec["value"]),
    "note_tag": lambda spec, user, tz: _notes(kind=HandNote.Kind.TAG, value=spec["value"].lower()),
    "tournament": lambda spec, user, tz: Q(tournament_id__in=spec["value"]),
}


def _faced(spec):
    """Bets by others on a street that the hero answered, of a size in the spec's range."""
    return HandBet.objects.filter(
        _between("size", spec), hand=OuterRef("pk"), street=spec["street"], is_hero=False
    ).exclude(hero_response="")


def _any_of(qs):
    q = Q(pk__in=[])
    for member in qs:
        q |= member
    return q


def _bb_between(column, spec):
    """A chip column between so many big blinds."""
    q = Q(big_blind__gt=0)
    if "min" in spec:
        q &= Q(**{f"{column}__gte": F("big_blind") * spec["min"]})
    if "max" in spec:
        q &= Q(**{f"{column}__lte": F("big_blind") * spec["max"]})
    return q


def shareable(spec):
    """A spec with every condition that names a player taken out, for sharing: opponents' names stay private
    (feature ideas, section 7.6). A group left empty goes too."""
    if "all" in spec or "any" in spec:
        key = "all" if "all" in spec else "any"
        members = [kept for member in spec[key] if (kept := shareable(member)) is not None]
        return {key: members} if members else None
    if "not" in spec:
        kept = shareable(spec["not"])
        return {"not": kept} if kept is not None else None
    return None if spec["field"] in ("opponent", "tournament") else spec

