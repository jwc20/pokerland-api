"""Play it out (pokerland-practice-mode.md, 3.4, 4.1 and 7.2): whole hands at a practice table of two to nine seats,
against bots, from a fresh deal or from one of the user's own decisions.

- **From a deal.** You and up to eight bots: each a style's profile (practice.bots), or modelled on one of your own
  opponents from their statistics in your hands (FND-6), drawn towards a typical player's while their sample is
  small. The table deals hand after hand at blinds of 50 and 100; a busted stack buys in again.
- **From a spot.** One of your hands, at least a day old, from the decision a spot asked about: the seats, the stacks
  and the cards dealt by then as they were, the cards still to come from the rest of the deck. The others replay
  what they did until your line differs, or a card comes that wasn't dealt by then; from there bots play them, each
  modelled on that player. A player whose cards weren't shown gets two from the rest of the deck, from the hands
  their line before the spot makes likely. After it, the table deals on with the same players.

The bots are weak on purpose, and this mode stays out of every score (the main doc's risk 2); the page says the
opponents are bots. Hold'em only: the profiles play hold'em.
"""

import random

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from hands import ranges
from hands.models import HandPlayer, Opponent
from practice import bots
from practice.generators import CARDS
from practice.models import PracticeHand, PracticeTable
from practice.sets import MIN_AGE, hand_data
from practice.spots import pending, postflop_order
from practice.table import TableHand, shuffled_deck

HERO = "You"
BLINDS = (50, 100)
SEATS = range(2, 10)
OPPONENTS = {
    "mixed": "A mix of the four styles",
    "tag": "Tight-aggressive",
    "lag": "Loose-aggressive",
    "station": "Calling stations",
    "rock": "Rocks",
    "mine": "Your own opponents",
}
MIN_HANDS = 30  # an opponent of yours needs this many hands with you to be modelled
MOVES = ("fold", "check", "call", "bet", "raise")
LIKELY_TRIES = 200  # draws of an unknown player's cards before taking any


class PlayError(ValueError):
    """Something the table can't do now, such as acting out of turn, or a hand it can't rebuild."""


# Profiles ------------------------------------------------------------------------------------------------------


def seat_openings(user, **filters):
    """Raises first in by seat, {position: (did, could)}, over the user's opponents' HandPlayer rows."""
    rows = (
        HandPlayer.objects.filter(user=user, is_hero=False, **filters)
        .values("position")
        .annotate(did=Sum("rfi_did", default=0), could=Sum("rfi_could", default=0))
        .order_by()
    )
    return {row["position"]: (row["did"], row["could"]) for row in rows}


def typical_profile(user):
    """A typical player in the user's games: their opponents' statistics together, drawn towards the tight-aggressive
    profile while there are few of them."""
    totals = {}
    for counters in Opponent.objects.filter(user=user).values_list("counters", flat=True):
        for key, value in counters.items():
            totals[key] = totals.get(key, 0) + value
    return bots.calibrated(totals, seat_openings(user))


def opponent_profile(user, opponent, typical):
    """One of the user's opponents as a bot: their statistics, drawn towards a typical player's."""
    seats = seat_openings(user, hand__site=opponent.site, name=opponent.name)
    return bots.calibrated(opponent.counters, seats, typical)


def modelled(opponent, typical, user):
    """A bot seat's description of a real opponent, and its profile."""
    return {
        "profile": opponent_profile(user, opponent, typical),
        "style": "",
        "label": f"Modelled on {opponent.name}",
        "based_on": {"id": opponent.pk, "name": opponent.name, "hands": opponent.hands},
    }


def styled(style):
    return {"profile": bots.PROFILES[style], "style": style, "label": bots.STYLES[style], "based_on": None}


# Tables from a deal ------------------------------------------------------------------------------------------------


@transaction.atomic
def start_deal(user, seats=6, opponents="mixed", stack_bb=100, rng=None):
    """A table of `seats`: you and bots of the chosen kind, everyone `stack_bb` deep. Deals its first hand."""
    rng = rng or random.SystemRandom()
    stack = stack_bb * BLINDS[1]
    others = []
    if opponents == "mine":
        typical = typical_profile(user)
        found = Opponent.objects.filter(user=user, hands__gte=MIN_HANDS).order_by("-hands")[: seats - 1]
        others = [{"name": opponent.name, **modelled(opponent, typical, user)} for opponent in found]
    while len(others) < seats - 1:
        style = rng.choice(sorted(bots.PROFILES)) if opponents in ("mixed", "mine") else opponents
        others.append({"name": f"Bot {len(others) + 1}", **styled(style)})
    rows = [{"seat": 1, "name": HERO, "stack": stack, "buy_in": stack}]
    rows += [{"seat": number, "stack": stack, "buy_in": stack, **bot} for number, bot in enumerate(others, start=2)]
    table = PracticeTable.objects.create(
        user=user,
        kind="play",
        seats=rows,
        small_blind=BLINDS[0],
        big_blind=BLINDS[1],
        button_seat=rng.randrange(1, seats + 1),
    )
    deal(table, rng)
    return table


def hero_of(table):
    return next(seat["name"] for seat in table.seats if not seat.get("profile"))


def deal(table, rng=None):
    """Deals the next hand from a fresh deck, and plays the bots until it is the user's turn or the hand is over."""
    seats = [{key: seat[key] for key in ("seat", "name", "stack")} for seat in table.seats if seat["stack"] > 0]
    row = PracticeHand.objects.create(
        table=table,
        number=table.hands_played + 1,
        small_blind=table.small_blind,
        big_blind=table.big_blind,
        button_seat=table.button_seat,
        stacks={seat["name"]: seat["stack"] for seat in seats},
        deck=shuffled_deck(rng),
    )
    advance(table, row, rebuild(table, row), rng)
    return row


def rebuild(table, row):
    """A practice hand's PokerKit state, from its deck and moves."""
    seats = [
        {"seat": seat["seat"], "name": seat["name"], "stack": row.stacks[seat["name"]]}
        for seat in table.seats
        if seat["name"] in row.stacks
    ]
    return TableHand(seats, row.button_seat, row.small_blind, row.big_blind, row.deck, row.moves, table.ante)


def current_hand(table):
    return table.hands.order_by("-number").first()


def on_script(row, hand):
    """Whether the hand is still the user's own: every move since the spot as it was, and no card dealt since."""
    if not row.script:
        return False
    since = hand.moves[row.scripted :]
    board = len(hand.replay(hand.names[0])["board"])
    return since == row.script[: len(since)] and len(since) < len(row.script) and board <= row.script_board


def advance(table, row, hand, rng=None):
    """Plays the bots until the user is to act or the hand is over, and saves the hand."""
    rng = rng or random.SystemRandom()
    hero = hero_of(table)
    while hand.actor not in (None, hero):
        name = hand.actor
        if on_script(row, hand) and row.script[len(hand.moves) - row.scripted][0] == name:
            _, action, amount = row.script[len(hand.moves) - row.scripted]
            hand.act(name, action, amount)
            continue
        seat = next(seat for seat in table.seats if seat["name"] == name)
        hand.act(name, *bots.move(pending(hand.replay(name)), hand.legal(), seat, rng))
    row.moves = hand.moves
    row.replay = hand.replay(hero)
    if hand.finished:
        finish_hand(table, row, hand)
    else:
        row.save()


def finish_hand(table, row, hand):
    """Ends a hand: the stacks carry over and the button moves on."""
    row.finished = True
    row.phh = hand.hand_history().dumps()
    row.save()
    stacks = hand.stacks()
    for seat in table.seats:
        if seat["name"] in stacks:
            seat["stack"] = stacks[seat["name"]]
    table.hands_played = row.number
    numbers = sorted(seat["seat"] for seat in table.seats)
    table.button_seat = next((number for number in numbers if number > row.button_seat), numbers[0])
    table.save()


@transaction.atomic
def act(table, action, amount=None):
    """The user's move; then the bots play on."""
    row = current_hand(table)
    if row is None or row.finished:
        raise PlayError("The hand is over.")
    hand = rebuild(table, row)
    if hand.actor != hero_of(table):
        raise PlayError("It isn't your turn.")
    try:
        hand.act(hand.actor, action, amount)
    except ValueError as error:
        raise PlayError(str(error)) from None
    advance(table, row, hand)
    return row


@transaction.atomic
def next_hand(table, rng=None):
    """Deals the next hand once the last is over. A busted stack, yours too, buys in again for what it began with."""
    row = current_hand(table)
    if row and not row.finished:
        raise PlayError("The hand isn't over.")
    for seat in table.seats:
        if seat["stack"] <= 0:
            seat["stack"] = seat["buy_in"]
    table.save(update_fields=["seats"])
    return deal(table, rng)


# Tables from a spot ------------------------------------------------------------------------------------------------


@transaction.atomic
def start_spot(user, scenario, rng=None):
    """A table that plays one of the user's hands on from the decision a spot asked about; PlayError when the hand
    can't be played here (not hold'em, too recent, or blinds a practice table doesn't post)."""
    rng = rng or random.SystemRandom()
    hand = scenario.hand
    if scenario.source != "own_hand" or hand is None or hand.user_id != user.pk:
        raise PlayError("Only a spot from one of your own hands can be played out.")
    if hand.game != "Hold'em No Limit":
        raise PlayError("Only no-limit hold'em hands can be played out: the bots play hold'em.")
    if hand.played_at > timezone.now() - MIN_AGE:
        raise PlayError("A hand has to be a day old to be played out.")
    data = hand_data(hand)
    step = scenario.step
    events = data["events"]
    seats = [{"seat": player["seat"], "name": player["name"], "stack": player["stack"]} for player in data["players"]]
    order = [seat["name"] for seat in _ordered(seats, data["button_seat"])]
    before = [_move(event) for event in events[:step] if event["type"] in MOVES]
    after = [_move(event) for event in events[step:] if event["type"] in MOVES]
    board = next((event["board"] for event in reversed(events[:step]) if event["type"] == "street"), [])
    deck = _spot_deck(data, events[:step], order, board, rng)
    typical = typical_profile(user)
    known = {opponent.name: opponent for opponent in Opponent.objects.filter(user=user, site=hand.site, name__in=order)}
    rows = []
    for seat in seats:
        row = {**seat, "buy_in": seat["stack"]}
        if seat["name"] != data["hero"]:
            opponent = known.get(seat["name"])
            if opponent:
                row.update(modelled(opponent, typical, user))
            else:
                row.update(profile=typical, style="", label="A typical player", based_on=None)
        rows.append(row)
    table = PracticeTable.objects.create(
        user=user,
        kind="play",
        seats=rows,
        small_blind=hand.small_blind,
        big_blind=hand.big_blind,
        ante=data.get("ante") or 0,
        currency=hand.currency,
        button_seat=data["button_seat"],
        scenario=scenario,
    )
    row = PracticeHand(
        table=table,
        number=1,
        small_blind=hand.small_blind,
        big_blind=hand.big_blind,
        button_seat=data["button_seat"],
        stacks={seat["name"]: seat["stack"] for seat in seats},
        deck=deck,
        moves=before,
        scripted=len(before),
        script=after,
        script_board=len(board),
    )
    try:
        rebuilt = rebuild(table, row)
    except ValueError:
        raise PlayError("This hand can't be played out here: its moves don't replay at a practice table.") from None
    if not _same(rebuilt.replay(data["hero"])["events"], events[:step]):
        raise PlayError("This hand can't be played out here: its blinds or antes don't fit a practice table.")
    row.replay = rebuilt.replay(data["hero"])
    row.save()
    return table


def _ordered(seats, button_seat):
    by_seat = {seat["seat"]: seat for seat in seats}
    return [by_seat[number] for number in postflop_order(seats, button_seat)]


def _move(event):
    """A stored hand's move as a practice table makes it: [name, action, the bet it makes, for a bet or a raise]."""
    kind = event["type"]
    if kind == "raise":
        return [event["player"], kind, event["to"]]
    if kind == "bet":
        return [event["player"], kind, event["amount"]]
    return [event["player"], kind, None]


def _spot_deck(data, events, order, board, rng):
    """The deck for a hand played on from a spot: everyone's hole cards in dealing order, those known as they were and
    the rest likely ones; then the board dealt by then in its place, and the cards still to come from what's left."""
    known = {player["name"]: list(player["cards"]) for player in data["players"] if player["cards"]}
    used = {card for cards in known.values() for card in cards} | set(board)
    rest = [card for card in CARDS if card not in used]
    rng.shuffle(rest)
    lines = _preflop_lines(events)
    for name in order:
        if name not in known:
            known[name] = _likely(rest, lines.get(name), rng)
    hole = [card for name in order for card in known[name]]
    rest = [card for card in rest if card not in hole]
    # A burn before each street: a burn and the flop, a burn and the turn, a burn and the river.
    streets = [board[:3], board[3:4], board[4:5]]
    dealt = []
    for count, cards in zip((3, 1, 1), streets, strict=True):
        dealt.append(rest.pop())
        dealt += cards + [rest.pop() for _ in range(count - len(cards))]
    return "".join(hole + dealt + rest)


def _preflop_lines(events):
    """What each player did before the flop by the spot: "raise", "call", or nothing yet."""
    lines = {}
    for event in events:
        if event["street"] != "preflop" or event["type"] not in ("call", "raise"):
            continue
        if lines.get(event["player"]) != "raise":
            lines[event["player"]] = event["type"]
    return lines


def _likely(rest, line, rng):
    """Two cards from the rest of the deck, from the hands a line before the flop makes likely: the top quarter for a
    raise, the top half for a call, any for no move yet. Taken from the deck."""
    wanted = ranges.top(25) if line == "raise" else ranges.top(50) if line == "call" else None
    for _ in range(LIKELY_TRIES if wanted else 1):
        first, second = rng.sample(range(len(rest)), 2)
        cards = [rest[first], rest[second]]
        if wanted is None or ranges.combo_of(cards) in wanted:
            break
    for card in cards:
        rest.remove(card)
    return cards


def _same(rebuilt, stored):
    """Whether a rebuilt hand's events match a stored one's: each post and move, by whom and for how much."""
    def key(event):
        return (event["type"], event.get("player"), event.get("amount"))

    kinds = ("post", *MOVES)
    return [key(e) for e in rebuilt if e["type"] in kinds] == [key(e) for e in stored if e["type"] in kinds]


# What the client sees -------------------------------------------------------------------------------------------


def state(table):
    """A table as the user sees it: the hand so far, their moves when it is their turn, and who the bots are."""
    row = current_hand(table)
    hero = hero_of(table)
    hand = rebuild(table, row) if not row.finished else None
    turn = hand is not None and hand.actor == hero
    net = next((player["net"] for player in row.replay["players"] if player["name"] == hero), 0)
    start = next(seat["buy_in"] for seat in table.seats if seat["name"] == hero)
    now = next(seat["stack"] for seat in table.seats if seat["name"] == hero)
    return {
        "id": table.pk,
        "hand_number": row.number,
        "hands_played": table.hands_played,
        "small_blind": row.small_blind,
        "big_blind": row.big_blind,
        "hand": {
            "game": "Hold'em No Limit",
            "currency": table.currency,
            "small_blind": row.small_blind,
            "big_blind": row.big_blind,
            "ante": table.ante,
            "tournament_id": "",
            "button_seat": row.button_seat,
            "max_seats": len(table.seats),
            "hero": hero,
            "players": row.replay["players"],
            "events": row.replay["events"],
        },
        "hand_over": row.finished,
        "hand_net_bb": round(net / row.big_blind, 2) if row.finished else None,
        "legal": hand.legal() if turn else None,
        "seats": [
            {
                "seat": seat["seat"],
                "name": seat["name"],
                "hero": seat["name"] == hero,
                "label": seat.get("label", ""),
                "style": seat.get("style", ""),
                "based_on": seat.get("based_on"),
            }
            for seat in table.seats
        ],
        "result_bb": round((now - start) / table.big_blind, 2),
        "spot": _spot_view(table, row, hand),
    }


def _spot_view(table, row, hand):
    """Where a table from a spot stands: the spot, and whether the others still replay the hand as it was."""
    if table.scenario_id is None:
        return None
    scenario = table.scenario
    replaying = row.number == 1 and hand is not None and on_script(row, hand)
    return {"scenario": scenario.pk, "hand": scenario.hand_id, "step": scenario.step, "on_script": replaying}


def recent(user):
    """The user's Play it out tables, the latest first, with how many hands each has had."""
    return (
        PracticeTable.objects.filter(user=user, kind="play")
        .annotate(dealt=Count("hands"))
        .order_by("-updated")[:20]
    )
