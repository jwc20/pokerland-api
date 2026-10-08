"""The hero's decisions in a hand, as the practice spots and the playbook's rules see them.

`decisions(hand)` walks a hand's events, in the replay's format (tracker.parsing.pokerstars), and returns the
context of each of the hero's folds, checks, calls, bets and raises: what they faced and its price, the stacks
and the pot in big blinds, their position and line so far, and from the flop on what they held. `pending(hand)`
returns the same for the decision a practice table is waiting on. The numbers are the decision panel's
(pokerland-client's src/decision.ts), worked out the same way.

A hand is a dict with the replay's `players`, `events` and `button_seat`, its `big_blind` and its `hero`: what
`pokerstars.extract` returns, or a stored Hand's replay with its columns. Like tracker.parsing this module never
imports Django, so it runs on fixture files, on stored hands and at a practice table alike.
"""

from tracker.parsing.facts import draws, made_hand

MOVES = ("fold", "check", "call", "bet", "raise")
POSTFLOP = ("flop", "turn", "river")

# What the playbook's rules call a hand after the flop, from its made hand and draws (tracker.parsing.facts):
# a good hand, one that beats bluffs and little else, a draw with eight or more outs, or nothing.
HAND_CLASSES = ("nothing", "draw", "showdown_value", "strong")
STRONG = {
    "overpair",
    "top_pair_top_kicker",
    "top_pair",
    "two_pair",
    "set",
    "trips",
    "three_of_a_kind",
    "straight",
    "flush",
    "full_house",
    "four_of_a_kind",
    "straight_flush",
}
SHOWDOWN_VALUE = {"second_pair", "bottom_pair", "pocket_pair", "underpair", "one_pair"}  # one_pair: Omaha's
STRONG_DRAWS = {"nut_flush_draw", "flush_draw", "open_ended", "double_gutshot"}
# The made hands in words, as the coach and the read card say them.
HAND_NAMES = {
    "high_card": "nothing",
    "overcards": "two overcards",
    "underpair": "an underpair",
    "pocket_pair": "a pocket pair under the top card",
    "bottom_pair": "bottom pair",
    "second_pair": "second pair",
    "top_pair": "top pair",
    "top_pair_top_kicker": "top pair, top kicker",
    "overpair": "an overpair",
    "one_pair": "one pair",
    "two_pair": "two pair",
    "trips": "trips",
    "set": "a set",
    "three_of_a_kind": "three of a kind",
    "straight": "a straight",
    "flush": "a flush",
    "full_house": "a full house",
    "four_of_a_kind": "four of a kind",
    "straight_flush": "a straight flush",
}


def hand_class(made, drawing=()):
    """The class of a made hand and its draws: strong, showdown_value, draw or nothing."""
    if made in STRONG:
        return "strong"
    if made in SHOWDOWN_VALUE:
        return "showdown_value"
    if STRONG_DRAWS & set(drawing):
        return "draw"
    return "nothing"


def decisions(hand, hero=None):
    """The context of each decision `hero` (the hand's hero unless given) made in `hand`, in order.

    Each has the event index of the move as `step` (the replay step before it is the table the decision
    faced) and what the hero did as `move`.
    """
    table = _Table(hand, hero or hand["hero"])
    found = []
    for step, event in enumerate(hand["events"]):
        if event.get("player") == table.hero and event["type"] in MOVES:
            found.append({"step": step, **table.context(), "move": table.move(event)})
        table.apply(event)
    return found


def pending(hand, hero=None):
    """The context of the decision `hero` faces once every event in `hand` has happened, as at a practice table."""
    table = _Table(hand, hero or hand["hero"])
    for event in hand["events"]:
        table.apply(event)
    return {"step": len(hand["events"]), **table.context()}


def postflop_order(players, button_seat):
    """Seats in the order they act after the flop: the first seat after the button first, the button last."""
    seats = sorted(player["seat"] for player in players)
    button = seats.index(button_seat) if button_seat in seats else len(seats) - 1
    return [*seats[button + 1 :], *seats[: button + 1]]


class _Seat:
    def __init__(self, row):
        self.name = row["name"]
        self.seat = row["seat"]
        self.position = row["position"]
        self.start = row["stack"]
        self.stack = row["stack"]
        self.bet = 0  # in front of the player on this street
        self.folded = False
        self.all_in = False


class _Table:
    """The table as the events go by, seen from one player's seat."""

    def __init__(self, hand, hero):
        self.hero = hero
        self.bb = hand["big_blind"] or 1
        self.dealt = len(hand["players"])
        self.seats = {row["name"]: _Seat(row) for row in hand["players"]}
        order = postflop_order(hand["players"], hand["button_seat"])
        self.order = {seat: i for i, seat in enumerate(order)}
        own = next((row for row in hand["players"] if row["name"] == hero), None)
        self.cards = list(own["cards"]) if own else []
        self.pot = 0  # in the middle, without the bets still in front of the players
        self.street = "preflop"
        self.board = []
        self.facing = None  # the last bet or raise on this street, and what was in the middle before it
        self.callers = 0  # calls since `facing`, or since the street began; before the flop with no raise, limpers
        self.checks = 0  # checks on this street
        self.raisers = []  # who raised before the flop, in turn
        self.lines = {}  # street -> the hero's moves on it
        self.bets_faced = 0  # decisions after the flop at which the hero faced a bet or a raise
        self.spr = None
        self.increment = self.bb  # the least a raise must add to the bet: the last bet or raise's own size

    def apply(self, event):
        kind = event["type"]
        seat = self.seats.get(event.get("player"))
        amount = event.get("amount", 0)
        if kind == "post":
            dead = event.get("dead", 0)
            self.put_in(seat, amount, event, dead)
        elif kind == "deal" and seat and seat.name == self.hero:
            self.cards = list(event.get("cards", []))
        elif kind in MOVES:
            self.act(seat, kind, amount, event)
        elif kind == "street":
            self.new_street(event)
        elif kind == "return":
            back = min(amount, seat.bet)
            seat.bet -= back
            self.pot -= amount - back
            seat.stack += amount

    def put_in(self, seat, amount, event, dead=0):
        seat.stack -= amount
        seat.bet += amount - dead
        self.pot += dead
        seat.all_in = seat.all_in or bool(event.get("all_in"))

    def act(self, seat, kind, amount, event):
        hero = seat.name == self.hero
        if hero:
            if self.street in POSTFLOP and self.to_call(seat) > 0:
                self.bets_faced += 1
            self.lines.setdefault(self.street, []).append(kind)
        if kind in ("bet", "raise"):
            self.facing = {"event": event, "pot_before": self.middle()}
            self.increment = max(self.increment, event.get("by", amount))
            self.callers = 0
            self.checks = 0
            if self.street == "preflop":
                self.raisers.append(seat.name)
        elif kind == "call" and not hero:
            self.callers += 1
        elif kind == "check" and not hero:
            self.checks += 1
        if kind == "fold":
            seat.folded = True
        elif amount:
            self.put_in(seat, amount, event)

    def new_street(self, event):
        for seat in self.seats.values():
            self.pot += seat.bet
            seat.bet = 0
        self.street = event["street"]
        self.board = list(event.get("board", self.board))
        self.increment = self.bb
        self.facing = None
        self.callers = 0
        self.checks = 0
        hero = self.seats.get(self.hero)
        if self.street == "flop" and hero and not hero.folded and self.pot:
            self.spr = round(self.effective(hero) / self.pot, 2)

    def middle(self):
        """Chips in the middle: the pot and the bets in front of the players."""
        return self.pot + sum(seat.bet for seat in self.seats.values())

    def to_call(self, seat):
        top = max(other.bet for other in self.seats.values())
        return max(0, min(top - seat.bet, seat.stack))

    def price(self, seat):
        """What calling costs `seat`, and the pot after the call they can win: all-in, no more than their own total."""
        to_call = self.to_call(seat)
        all_in = 0 < to_call == seat.stack
        if not all_in:
            return to_call, self.middle() + to_call, all_in
        # Nothing goes back to a player while there is betting left to do, so a stack's drop is what was put in.
        total = seat.start - seat.stack + to_call
        pot = sum(min(total if other is seat else other.start - other.stack, total) for other in self.seats.values())
        return to_call, pot, all_in

    def effective(self, seat):
        """The most `seat` can still lose: their stack, or what the biggest stack still in can match."""
        others = [other for other in self.seats.values() if other is not seat and not other.folded]
        return min(seat.stack, max([0, *(other.stack + other.bet - seat.bet for other in others)]))

    def in_position(self, seat):
        """Whether `seat` acts last after the flop; None when no opponent still in can act."""
        able = [other for other in self.seats.values() if other is not seat and not other.folded and not other.all_in]
        if not able:
            return None
        return all(self.order[other.seat] < self.order[seat.seat] for other in able)

    def raise_sizes(self, seat):
        """The least and the most a raise can make `seat`'s bet, or None when nobody left can call one."""
        others = [other for other in self.seats.values() if other is not seat and not other.folded]
        if seat.stack <= self.to_call(seat) or all(other.all_in for other in others):
            return None
        most = seat.bet + seat.stack
        return min(max(other.bet for other in self.seats.values()) + self.increment, most), most

    def bb_of(self, chips):
        return round(chips / self.bb, 2)

    def context(self):
        """What the hero's decision faces now."""
        hero = self.seats[self.hero]
        to_call, pot_if_call, all_in_call = self.price(hero)
        position = self.in_position(hero)
        live = [seat for seat in self.seats.values() if not seat.folded]
        aggressor = self.raisers[-1] if self.raisers else None
        context = {
            "street": self.street,
            "players": len(live),
            "players_dealt": self.dealt,
            "heads_up": self.dealt == 2,
            "multiway": len(live) > 2,
            "hero_position": hero.position,
            "position": None if position is None else "in" if position else "out",
            "aggressor": None if aggressor is None else "hero" if aggressor == self.hero else "opponent",
            "preflop": self.preflop_line(aggressor),
            "situation": _situation(len(self.raisers), self.callers) if self.street == "preflop" else None,
            "facing": "none",
            "facing_all_in": False,
            "facing_to": None,
            "facing_bb": None,
            "facing_pot": None,
            "bettor": None,
            "bet": None,
            "pot_before": None,
            "callers": self.callers,
            "checks": self.checks,
            "to_call": to_call,
            "to_call_bb": self.bb_of(to_call),
            "pot": self.middle(),
            "pot_bb": self.bb_of(self.middle()),
            "pot_if_call": pot_if_call,
            "call_all_in": all_in_call,
            "big_blind": self.bb,
            "equity_needed": None,
            "mdf": None,
            "in_front": hero.bet,
            "raise_sizes": self.raise_sizes(hero),
            "stack": hero.stack,
            "stack_bb": self.bb_of(hero.stack),
            "effective_bb": self.bb_of(self.effective(hero)),
            "spr": self.spr if self.street in POSTFLOP else None,
            "cards": self.cards,
            "board": self.board,
            "has_ace": any(card[0] == "A" for card in self.cards),
            "line": list(self.lines.get(self.street, [])),
            "previous": self.previous_line(),
            "bets_faced": self.bets_faced,
            **self.holding(),
        }
        if self.facing and to_call:
            event, before = self.facing["event"], self.facing["pot_before"]
            bettor = self.seats[event["player"]]
            # Only a bet or raise has a price worth weighing: limping into the blinds is not calling one.
            context.update(
                facing="raise" if event["type"] == "raise" or self.street == "preflop" else "bet",
                facing_all_in=bettor.all_in,
                facing_to=bettor.bet,
                facing_bb=self.bb_of(bettor.bet),
                facing_pot=round(event["amount"] / before, 3) if before else None,
                bettor=bettor.name,
                bet=event["amount"],
                pot_before=before,
                equity_needed=round(to_call / pot_if_call, 4),
            )
            if self.street in POSTFLOP:
                context["mdf"] = round(before / (before + event["amount"]), 4)
        return context

    def preflop_line(self, aggressor):
        """The hero's part before the flop, once it is over: raised (last), called_raise, or limped."""
        if self.street == "preflop":
            return None
        if aggressor is None:
            return "limped"
        return "raised" if aggressor == self.hero else "called_raise"

    def previous_line(self):
        """The hero's moves on the street before this one after the flop, as "check_call"; None on the flop."""
        if self.street not in POSTFLOP or self.street == "flop":
            return None
        moves = self.lines.get(POSTFLOP[POSTFLOP.index(self.street) - 1])
        return "_".join(moves) if moves else None

    def holding(self):
        """What the hero holds on the board: the made hand, the draws and their class; nothing before the flop."""
        if self.street not in POSTFLOP or len(self.board) < 3 or not self.cards:
            return {"made": None, "draws": [], "hand_class": None, "pair_or_better": False}
        made = made_hand(self.cards, self.board)
        drawing = draws(self.cards, self.board) if len(self.cards) == 2 and len(self.board) < 5 else []
        held = hand_class(made, drawing)
        paired = held in ("strong", "showdown_value")
        return {"made": made, "draws": drawing, "hand_class": held, "pair_or_better": paired}

    def move(self, event):
        """What the hero did: the action, and for a call, bet or raise its chips, in big blinds and against the pot."""
        kind = event["type"]
        move = {"action": kind, "all_in": bool(event.get("all_in"))}
        amount = event.get("amount", 0)
        if kind in ("call", "bet", "raise"):
            move.update(amount=amount, amount_bb=self.bb_of(amount))
        if kind in ("bet", "raise"):
            before = self.middle()
            to = event.get("to", self.seats[self.hero].bet + amount)
            size = round(amount / before, 3) if before else None
            move.update(to=to, to_bb=self.bb_of(to), pot_before=before, size=size)
        return move


def _situation(raises, callers):
    """What a decision before the flop faces, as tracker.parsing.facts names it."""
    if raises == 0:
        return "limped" if callers else "unopened"
    return ("raised", "3bet", "4bet+")[min(raises, 3) - 1]
