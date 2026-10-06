"""Reads PokerStars hand histories with PokerKit.

PokerKit's `PokerStarsParser` turns a hand into a hand history in the PHH
notation (https://pokerkit.readthedocs.io/en/stable/notation.html), and
iterating a hand history plays it through PokerKit's rules engine. `extract`
does both and turns PokerKit's operations into what the game history and the
replay show. It returns plain data, so it runs on fixture files offline.

PokerKit's parser reads no-limit hold'em cash games without antes. The subclass
below extends it to what PokerStars histories hold: antes, a returning player's
dead small blind, pot-limit Omaha, Zoom hand numbers, times in UTC, and the
rake, which PokerKit needs to pay the winners what PokerStars paid them.
Amounts are integers: chips, or cents in games played for money.
"""

import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from zoneinfo import ZoneInfo

from pokerkit import (
    AntePosting,
    BetCollection,
    BlindOrStraddlePosting,
    BoardDealing,
    Card,
    CheckingOrCalling,
    ChipsPushing,
    CompletionBettingOrRaisingTo,
    Folding,
    HoleCardsShowingOrMucking,
    HoleDealing,
    notation,
)

SITE = "pokerstars"
GAMES = {"Hold'em No Limit": "NT", "Omaha Pot Limit": "PO"}  # PokerStars' names, PokerKit's variant codes
CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
TIMESTAMP = re.compile(r"(?P<date>\d{4}/\d{1,2}/\d{1,2}) (?P<time>\d{1,2}:\d{2}:\d{2})(?: (?P<zone>[A-Z]+))?")
MONEY = re.compile(r"\([^\d\s(][\d.,]+ in chips")  # a stack such as ($10.37 in chips)
CHAT = re.compile(r'^.+ said, ".*"$\n?', re.MULTILINE)
STREETS = {3: "flop", 4: "turn", 5: "river"}  # by the number of board cards


class HandError(ValueError):
    """The text is not a hand PokerKit can read."""


class PokerStarsParser(notation.PokerStarsParser):
    """PokerKit's PokerStars parser, extended to the hands PokerStars writes."""

    VARIANT = re.compile(rf" (?P<variant>{'|'.join(GAMES)}) ")
    VARIANTS = GAMES
    ANTE_POSTING = re.compile(r"(?P<player>.+): posts the ante \D?(?P<ante>[0-9.,]+)")
    # A player returning to the table posts both blinds: the big blind is live, the small blind dead.
    DEAD_BLINDS = re.compile(r"(?P<player>.+): posts small & big blinds \D?(?P<amount>[0-9.,]+)")
    MUCKED = re.compile(
        r"^Seat \d+: (?P<player>.+?)(?: \((?:button|small blind|big blind)\))* mucked \[(?P<cards>.+)\]"
    )
    BIG_BLIND = re.compile(r"/\D?(?P<_big_blind>[0-9.,]+)(?: [A-Z]{3})?\)")
    VARIABLES = {
        "hand": (re.compile(r"^PokerStars (?:Zoom |Home Game )?(?:Hand|Game) #(?P<hand>\d+):"), int),
        "event": (re.compile(r": (?P<event>Tournament #\d+),"), str),
        "table": (re.compile(r"^Table '(?P<table>.+)'", re.MULTILINE), str),
        "seat_count": (re.compile(r" (?P<seat_count>\d+)-max\b"), int),
        "currency": (re.compile(r"/\D?[0-9.,]+ (?P<currency>[A-Z]{3})\)"), str),
        "currency_symbol": (re.compile(r"\((?P<currency_symbol>[^\d\s(])[0-9.,]+ in chips"), str),
        # PHH has no fields for these; names starting with _ are user-defined.
        "_small_blind": (re.compile(r"\(\D?(?P<_small_blind>[0-9.,]+)/"), None),
        "_big_blind": (BIG_BLIND, None),
        "_play_money": (re.compile(r"^Table .*(?P<_play_money>\(Play Money\))", re.MULTILINE), bool),
        "_rake": (re.compile(r"^Total pot .*\| Rake \D?(?P<_rake>[0-9.,]+)", re.MULTILINE), None),
    }
    PLAYER_VARIABLES = {}  # PokerKit's `winnings` misreads the summary; extract() fills it in

    def read(self, text, parse_value):
        """The hand history of the one hand in `text`."""
        try:
            return self._parse(text, parse_value)
        except (KeyError, ValueError) as error:
            raise HandError(f"PokerKit could not read hand {text.split(':', 1)[0]!r}: {error}") from error

    def dead_blinds(self, text, parse_value):
        """The dead part of each "small & big blinds" post, by player."""
        dead = {}
        for line in text.splitlines():
            if match := self.DEAD_BLINDS.match(line):
                amount = parse_value(match["amount"])
                dead[match["player"]] = amount - min(amount, self.big_blind(text, parse_value))
        return dead

    def big_blind(self, text, parse_value):
        if not (match := self.BIG_BLIND.search(text)):
            raise ValueError("No stakes in the hand.")
        return parse_value(match["_big_blind"])

    def mucked_cards(self, text):
        """Cards of players who mucked at showdown, which only the summary shows."""
        return {
            match["player"]: [repr(card) for card in Card.parse(match["cards"])]
            for line in text.splitlines()
            if (match := self.MUCKED.match(line))
        }

    def _parse_antes(self, s, parse_value):
        antes = super()._parse_antes(s, parse_value)
        for player, dead in self.dead_blinds(s, parse_value).items():
            antes[player] += dead  # dead money, as an ante is
        return antes

    def _parse_blinds_or_straddles(self, s, parse_value):
        blinds = super()._parse_blinds_or_straddles(s, parse_value)
        for line in s.splitlines():
            if match := self.DEAD_BLINDS.match(line):
                # The live part. PokerKit makes it a post bet: a big blind from another seat.
                blinds[match["player"]] = min(parse_value(match["amount"]), self.big_blind(s, parse_value))
        return blinds

    def _parse_variables(self, s, parse_value):
        variables = super()._parse_variables(s, parse_value)
        started = played_at(s.split("\n", 1)[0])
        variables.update(time=started.time(), day=started.day, month=started.month, year=started.year, time_zone="UTC")
        return variables


@cache
def eastern():
    return ZoneInfo("America/New_York")


def played_at(header):
    """The hand's start in UTC.

    PokerStars writes it in the zone the player chose, followed by Eastern Time
    in brackets unless that is the chosen zone. Older histories omit the zone:
    that is Eastern Time too.
    """
    stamps = {}
    for match in TIMESTAMP.finditer(header):
        stamps.setdefault(match["zone"] or "ET", f"{match['date']} {match['time']}")
    for zone in ("UTC", "GMT", "ET"):
        if zone in stamps:
            tz = eastern() if zone == "ET" else UTC
            return datetime.strptime(stamps[zone], "%Y/%m/%d %H:%M:%S").replace(tzinfo=tz).astimezone(UTC)
    raise HandError(f"No UTC or ET time in {header!r}.")


def units(scale):
    """PokerKit's value parser for a hand: whole chips, or cents (scale 100) for money."""

    def parse_value(raw):
        value = Decimal(raw.replace(",", "")) * scale
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    return parse_value


def middle_positions(count):
    """Names for the players between the big blind and the button, first to act first."""
    if count < 1:
        return []
    late = ["LJ", "HJ", "CO"][-(count - 1) :] if count > 1 else []
    early = [f"UTG+{i}" for i in range(1, count - len(late))]
    return ["UTG", *early, *late]


def positions(count):
    """Positions in PHH player order: the small blind first, the button last; heads-up the big blind first."""
    if count == 2:
        return ["BB", "BTN"]
    return ["SB", "BB", *middle_positions(count - 3), "BTN"]


def final_state(hh, rake):
    """PokerKit's state at the end of the hand, having taken the `rake` PokerStars took."""
    if rake:
        hh.rake = rake_by_pot(pot_amounts(final_state(hh, 0)), rake)
    *_, state = hh
    return state


def pot_amounts(state):
    """The pots PokerKit pushed to the winners, main pot first."""
    pots = defaultdict(int)
    for operation in state.operations:
        if isinstance(operation, ChipsPushing):
            pots[operation.pot_index] += operation.total_amount
    return [pots[index] for index in sorted(pots)]


def rake_by_pot(pots, rake):
    """A PokerKit rake function that takes `rake` from `pots` in proportion to their size.

    PokerKit asks for a pot's rake by its amount, possibly more than once, so the
    answer is looked up rather than counted down.
    """
    total = sum(pots)
    shares = [rake * pot // total for pot in pots]
    for i in sorted(range(len(pots)), key=lambda i: rake * pots[i] % total, reverse=True)[: rake - sum(shares)]:
        shares[i] += 1
    by_amount = dict(zip(pots, shares, strict=True))

    def take(amount, state=None):
        raked = min(by_amount.get(amount, 0), amount)
        return raked, amount - raked

    return take


def card_names(cards):
    return [repr(card) for card in cards]


def known(cards):
    return bool(cards) and not any(card.unknown_status for card in cards)


def extract(text):
    """Returns the hand in `text` as data. Raises HandError if PokerKit cannot read it."""
    text = CHAT.sub("", text)  # chat could pass for an action
    parse_value = units(100 if MONEY.search(text) else 1)
    parser = PokerStarsParser()
    hh = parser.read(text, parse_value)
    fields = hh.user_defined_fields
    rake = fields.get("_rake", 0)
    state = final_state(hh, rake)
    replay = _Replay(hh, state, parser.dead_blinds(text, parse_value), parser.mucked_cards(text))
    hh.currency = hh.currency or CURRENCIES.get(hh.currency_symbol)
    hh.finishing_stacks = list(state.stacks)
    hh.winnings = replay.won

    players = replay.players()
    hero = next((player for player in players if player["name"] == replay.hero), None)
    antes = [event["amount"] for event in replay.events if event.get("blind") == "ante"]
    return {
        "site": SITE,
        "hand_id": str(hh.hand),
        "played_at": datetime(hh.year, hh.month, hh.day, hh.time.hour, hh.time.minute, hh.time.second, tzinfo=UTC),
        "game": next(name for name, code in GAMES.items() if code == hh.variant),
        "currency": hh.currency or "",
        "play_money": fields.get("_play_money", False),
        "small_blind": fields["_small_blind"],
        "big_blind": fields["_big_blind"],
        "tournament_id": hh.event.removeprefix("Tournament #") if hh.event else "",
        "table": str(hh.table)[:64],
        "max_seats": hh.seat_count,
        "button_seat": hh.seats[-1],
        "hero": replay.hero,
        "hero_position": hero["position"] if hero else "",
        "hero_cards": hero["cards"] if hero else [],
        "hero_net": hero["net"] if hero else 0,
        "final_street": replay.street,
        "ante": max(antes, default=0),
        "total_pot": sum(replay.won) + rake,
        "rake": rake,
        "board": replay.board,
        "players": players,
        "events": replay.events,
        "phh": hh.dumps(),
    }


class _Replay:
    """Walks PokerKit's operations into the events the replay steps through.

    The events read like the PokerStars history: an uncalled bet goes back to
    its player, and a player left alone in the hand collects the pot along with
    their called bet, which PokerKit gives back separately.
    """

    def __init__(self, hh, state, dead_blinds, mucked):
        self.hh = hh
        self.names = list(hh.players)
        count = len(self.names)
        self.positions = positions(count)
        self.final_stacks = list(state.stacks)
        self.stacks = list(hh.starting_stacks)
        self.bets = [0] * count
        self.folded = [False] * count
        self.cards = [[] for _ in range(count)]
        self.won = [0] * count
        self.called = [0] * count  # a lone winner's called bet, collected with the pot
        self.board = []
        self.board_cards = []
        self.street = "preflop"
        self.events = []
        self.hero = ""
        self.dead_blinds = dead_blinds
        self.mucked = mucked
        self.hand_type = hh.create_game().hand_types[0]
        self.blinds_posted = False

        operations = state.operations
        # A player's last show-or-muck is their showdown: while an all-in board
        # runs out, PokerKit shows the cards it does not know as unknown ones.
        showdowns = {op.player_index: i for i, op in enumerate(operations) if isinstance(op, HoleCardsShowingOrMucking)}
        self.pot_count = len({op.pot_index for op in operations if isinstance(op, ChipsPushing)})
        for i, operation in enumerate(operations):
            self.apply(operation, at_showdown=showdowns.get(getattr(operation, "player_index", None)) == i)

    def add(self, type_, player=None, **fields):
        event = {"type": type_, "street": self.street}
        if player is not None:
            event["player"] = self.names[player]
        event.update((key, value) for key, value in fields.items() if value is not None and value is not False)
        self.events.append(event)

    def put_in(self, player, amount):
        self.stacks[player] -= amount
        self.bets[player] += amount
        return self.stacks[player] == 0  # all-in

    def apply(self, op, at_showdown):
        match op:
            case AntePosting(player_index=p, amount=amount):
                self.put_in(p, amount)
                blind = "dead small blind" if self.names[p] in self.dead_blinds else "ante"
                self.add("post", p, blind=blind, amount=amount, dead=amount)
            case BlindOrStraddlePosting(player_index=p, amount=amount):
                self.blinds_posted = True
                all_in = self.put_in(p, amount)
                self.add("post", p, blind=self.blind_name(p), amount=amount, all_in=all_in)
            case HoleDealing(player_index=p, cards=cards) if known(cards):
                self.hero = self.names[p]  # a history deals known cards to its own player only
                self.cards[p] = card_names(cards)
                self.add("deal", p, cards=self.cards[p])
            case BoardDealing(cards=cards):
                self.board_cards += cards
                self.board = card_names(self.board_cards)
                self.street = STREETS.get(len(self.board), self.street)
                self.add("street", cards=card_names(cards), board=self.board)
            case Folding(player_index=p):
                self.folded[p] = True
                self.add("fold", p)
            case CheckingOrCalling(player_index=p, amount=amount):
                all_in = self.put_in(p, amount)
                self.add("call" if amount else "check", p, amount=amount or None, all_in=all_in)
            case CompletionBettingOrRaisingTo(player_index=p, amount=to):
                previous = max(self.bets)
                amount = to - self.bets[p]
                all_in = self.put_in(p, amount)
                if previous:
                    self.add("raise", p, amount=amount, to=to, by=to - previous, all_in=all_in)
                else:
                    self.add("bet", p, amount=amount, all_in=all_in)
            case BetCollection():
                if self.blinds_posted:  # the antes collected before the blinds are in the pot already
                    self.return_uncalled_bet()
                self.bets = [0] * len(self.names)
            case HoleCardsShowingOrMucking(player_index=p, hole_cards=cards) if at_showdown:
                if self.street != "showdown":
                    self.street = "showdown"
                    self.add("street")
                if known(cards):
                    self.cards[p] = card_names(cards)
                    self.add("show", p, cards=self.cards[p], description=self.describe(cards))
                else:
                    self.cards[p] = self.mucked.get(self.names[p], self.cards[p])
                    self.add("muck", p, cards=self.cards[p] or None)
            case ChipsPushing(amounts=amounts, pot_index=index):
                pot = self.pot_name(index)
                for p, amount in enumerate(amounts):
                    if amount:
                        amount += self.called[p]
                        self.called[p] = 0
                        self.won[p] += amount
                        self.add("collect", p, amount=amount, pot=pot)

    def pot_name(self, index):
        """As PokerStars names pots: pot, or main pot and side pot, or side pot-1, side pot-2, ..."""
        if self.pot_count == 1:
            return "pot"
        if index == 0:
            return "main pot"
        return "side pot" if self.pot_count == 2 else f"side pot-{index}"

    def return_uncalled_bet(self):
        """The part of the biggest bet that nobody called goes back, as PokerStars writes it."""
        top = max(range(len(self.bets)), key=self.bets.__getitem__)
        called = sorted(self.bets)[-2]
        if self.bets[top] > called:
            self.stacks[top] += self.bets[top] - called
            self.add("return", top, amount=self.bets[top] - called)
        if self.folded.count(False) == 1:
            # Everyone else folded: PokerKit leaves the winner's called bet out of the pot.
            self.called[self.folded.index(False)] += called

    def blind_name(self, player):
        position = self.positions[player]
        if self.hh.blinds_or_straddles[player] < 0 or position == "BB":
            return "big blind"  # a negative blind is a new player's post, which PokerKit calls a post bet
        if position == "SB" or (position == "BTN" and len(self.names) == 2):  # heads-up, the button is the SB
            return "small blind"
        return "straddle"

    def describe(self, cards):
        """The shown hand as PokerKit ranks it, e.g. "Three of a kind"."""
        try:
            return self.hand_type.from_game(cards, self.board_cards).entry.label.value
        except ValueError:  # too few cards for a hand, e.g. no board yet
            return None

    def players(self):
        """Everyone dealt in, in seat order."""
        rows = [
            {
                "seat": seat,
                "name": name,
                "stack": start,
                "position": position,
                "cards": cards,
                "won": won,
                "net": end - start,
            }
            for seat, name, start, end, position, cards, won in zip(
                self.hh.seats,
                self.names,
                self.hh.starting_stacks,
                self.final_stacks,
                self.positions,
                self.cards,
                self.won,
                strict=True,
            )
        ]
        return sorted(rows, key=lambda row: row["seat"])
