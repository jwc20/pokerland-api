"""Hands played on the server: PokerKit deals them from a shuffled deck and checks every move.

A practice hand is a deck, shuffled when the hand starts, and the moves made so far. `TableHand` rebuilds
PokerKit's state from them on each request, so the cards still to come are fixed but unseen, and a move counts
only if PokerKit allows it. `replay(name)` turns the state's operations into the seats, events and board of the
stored hands' format (tracker.parsing.pokerstars), as one player saw them: the web app replays a practice hand
like any other, and practice.spots reads its decisions from either seat.

Django-free, like tracker.parsing.
"""

import random
from collections import deque

from pokerkit import Automation, Card, Deck, HandHistory, NoLimitTexasHoldem

from practice.spots import postflop_order
from tracker.parsing.pokerstars import replay

GAME = "Hold'em No Limit"
ACTIONS = ("fold", "check", "call", "bet", "raise")
# PokerKit runs everything but the deal and the players' moves; the cards come from the hand's own deck.
AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)


class IllegalMove(ValueError):
    """A move the rules don't allow now."""


def shuffled_deck(rng=None):
    """A standard deck in a random order, as one string of two-character cards: "AhKd7c..."."""
    cards = [repr(card) for card in Deck.STANDARD]
    (rng or random.SystemRandom()).shuffle(cards)
    return "".join(cards)


class TableHand:
    """A hand at a practice table, rebuilt from its deck and the moves made so far.

    `seats` lists the players dealt in as {"seat", "name", "stack"}. `moves` are [name, action, amount], the
    amount being the total a bet or raise makes the player's bet on the street, and None otherwise. `ante` is what
    each player antes, or {name: ante} for antes only some post, such as a big-blind ante.
    """

    def __init__(self, seats, button_seat, small_blind, big_blind, deck, moves=(), ante=0):
        by_seat = {seat["seat"]: seat for seat in seats}
        # PokerKit's order: the first to act after the flop first, the button last.
        self.seats = [by_seat[number] for number in postflop_order(seats, button_seat)]
        self.names = [seat["name"] for seat in self.seats]
        self.button_seat = button_seat
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.ante = ante
        antes = {self.names.index(name): chips for name, chips in ante.items()} if isinstance(ante, dict) else ante
        self.game = NoLimitTexasHoldem(AUTOMATIONS, True, antes, (small_blind, big_blind), big_blind)
        self.state = self.game([seat["stack"] for seat in self.seats], len(self.seats))
        self.state.deck_cards = deque(Card.parse(deck))
        while self.state.can_deal_hole():
            self.state.deal_hole(2)
        self.moves = []
        for name, action, amount in moves:
            self.act(name, action, amount)

    @property
    def actor(self):
        """Whose turn it is; None once the hand is over."""
        index = self.state.actor_index
        return None if index is None else self.names[index]

    @property
    def finished(self):
        return not self.state.status

    def cards(self, name):
        """A player's hole cards, which only the server and, once shown, the table know."""
        return [repr(card) for card in self.state.hole_cards[self.names.index(name)]]

    def stacks(self):
        """Each player's chips now, by name."""
        return dict(zip(self.names, self.state.stacks, strict=True))

    def legal(self):
        """What the player to act may do: the price, and the sizes a bet or raise may make their bet, to the chip."""
        state = self.state
        if state.actor_index is None:
            return None
        to_call = state.checking_or_calling_amount
        can_raise = state.can_complete_bet_or_raise_to()
        return {
            "to_call": to_call,
            "can_check": to_call == 0,
            "can_raise": can_raise,
            "raise_kind": "raise" if max(state.bets) else "bet",
            "min_to": state.min_completion_betting_or_raising_to_amount if can_raise else None,
            "max_to": state.max_completion_betting_or_raising_to_amount if can_raise else None,
            "bet": state.bets[state.actor_index],
            "stack": state.stacks[state.actor_index],
        }

    def act(self, name, action, amount=None):
        """Makes `name`'s move, then deals any cards it brings; IllegalMove if the rules don't allow it now."""
        state = self.state
        if action not in ACTIONS or name != self.actor:
            raise IllegalMove(f"It isn't {name}'s turn to {action}.")
        to_call = state.checking_or_calling_amount
        kind = action
        if action == "fold" and state.can_fold():  # not when checking is free
            state.fold()
        elif (action == "check" and to_call == 0) or (action == "call" and to_call > 0):
            state.check_or_call()
        elif action in ("bet", "raise") and amount is not None and state.can_complete_bet_or_raise_to(int(amount)):
            kind = "raise" if max(state.bets) else "bet"
            state.complete_bet_or_raise_to(int(amount))
        else:
            raise IllegalMove(f"{name} can't {action}{'' if amount is None else f' to {amount}'} now.")
        self.moves.append([name, kind, int(amount) if kind in ("bet", "raise") else None])
        while state.can_deal_board():
            state.deal_board()

    def hand_history(self):
        """The hand in PokerKit's PHH notation, with every player's cards: for the server's eyes."""
        hh = HandHistory.from_game_state(self.game, self.state)
        hh.players = list(self.names)
        hh.seats = [seat["seat"] for seat in self.seats]
        hh.seat_count = len(self.seats)
        return hh

    def replay(self, name):
        """The hand so far as `name` saw it, in the stored hands' replay format: their cards, and shown ones."""
        data = replay(self.hand_history(), self.state, name)
        return {
            **data,
            "hero": name,
            "button_seat": self.button_seat,
            "max_seats": len(self.seats),
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "ante": sum(self.ante.values()) if isinstance(self.ante, dict) else self.ante,
            "rake": 0,
            "total_pot": sum(player["won"] for player in data["players"]),
        }
