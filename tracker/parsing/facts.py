"""What each decision in a hand faced: the hand facts behind the statistics (FND-1 of the feature ideas).

`hand_facts` walks the events `pokerstars.extract` makes of a hand. For every
player it counts the did/could pairs a tracker's statistics are made of, as
PokerTracker defines them: how often a player did something ÷ how often they
could have. For the hand it works out the situation before the flop, the pot
and the stacks on each street, the board's texture, and what the hero held and
how they played each street. Every bet and raise is listed with its size, what
its maker held when their cards are known, and how it was answered.

Like the rest of tracker.parsing it never imports Django, so the parser tests
run it on the fixture files offline.
"""

from collections import Counter

from pokerkit import OmahaHoldemHand, StandardHighHand

from tracker.parsing import equity

RANKS = "23456789TJQKA"
MOVES = {"fold", "check", "call", "bet", "raise"}
AGGRESSIVE = {"bet", "raise"}
POSTFLOP = ("flop", "turn", "river")
STEAL_POSITIONS = {"CO", "BTN", "SB"}  # heads-up the button is the small blind, and is "BTN"

# Each statistic a player can have a chance at in a hand, and what it counts: HandPlayer's <name>_could
# and <name>_did columns.
STATS = {
    "vpip": "Put money in before the flop by choice: called or raised, not just posted a blind.",
    "pfr": "Raised before the flop.",
    "rfi": "Raised first in: the chance is an unopened pot, folded to the player.",
    "limp": "Called the big blind with no raise in front.",
    "cold_call": "Called a raise with no money in by choice yet.",
    "three_bet": "Re-raised a raise.",
    "fold_to_three_bet": "Opened with a raise, then folded to a re-raise.",
    "four_bet": "Re-raised a 3-bet.",
    "squeeze": "Re-raised a raise that had been called, with no money in by choice yet.",
    "steal": "Raised first in from the cutoff, the button or the small blind.",
    "fold_to_steal": "In a blind, folded to a steal.",
    "call_vs_steal": "In a blind, called a steal.",
    "three_bet_vs_steal": "In a blind, re-raised a steal.",
    "bb_defend": "In the big blind, called or re-raised a steal.",
    "cbet_flop": "Raised last before the flop, then bet the flop when it was checked to them.",
    "cbet_turn": "C-bet the flop and wasn't raised, then bet the turn when it was checked to them.",
    "cbet_river": "C-bet the turn and wasn't raised, then bet the river when it was checked to them.",
    "fold_to_cbet_flop": "Folded to a c-bet on the flop.",
    "fold_to_cbet_turn": "Folded to a c-bet on the turn.",
    "fold_to_cbet_river": "Folded to a c-bet on the river.",
    "donk_flop": "Bet the flop into the player who raised last before it, before they could act.",
    "check_raise": "Checked, then raised a bet on the same street: one chance a street.",
    "saw_flop": "Saw the flop: the chance is being dealt in.",
    "went_to_showdown": "Went to showdown: the chance is seeing the flop.",
    "won_at_showdown": "Won money at showdown: the chance is going to showdown.",
}
# Moves after the flop, counted for the aggression frequency: (bets + raises) ÷ (bets + raises + calls + folds).
POSTFLOP_ACTIONS = ("bets", "raises", "calls", "checks", "folds")
_ACTION_COUNT = {"bet": "bets", "raise": "raises", "call": "calls", "check": "checks", "fold": "folds"}

# Starting-hand groups from the Johns Hopkins course's hand classes [JHU 3; JHU 4], first match wins; "weak_ace"
# and "junk" catch the rest.
HAND_GROUPS = ("premium", "big_pair", "medium_pair", "small_pair", "big_ace", "suited_connector", "trouble")
ALL_HAND_GROUPS = (*HAND_GROUPS, "weak_ace", "junk")
_PREMIUM = {"AA", "KK", "QQ", "AK"}
_TROUBLE = {"AJ", "AT", "KQ", "KJ", "KT", "QJ", "QT", "JT"}  # good-looking hands that are often dominated

# Made hands after the flop by what they are worth (practice.spots names its hand classes from these): a good hand,
# one that beats bluffs and little else (Omaha's one_pair too), and the draws of eight outs or more.
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
SHOWDOWN_VALUE = {"second_pair", "bottom_pair", "pocket_pair", "underpair", "one_pair"}
STRONG_DRAWS = {"nut_flush_draw", "flush_draw", "open_ended", "double_gutshot"}
# How strong a hand was when its player bet, weakest first: the sizing report's classes (B4).
STRENGTHS = ("nothing", "draw", "weak", "strong", "nuts")
# Hold'em hands that can be the nuts: nothing weaker ever is, since a set is always possible.
_NUT_CANDIDATES = {"set", "trips", "straight", "flush", "full_house", "four_of_a_kind", "straight_flush"}
# Boards by what they let happen, first match wins: three or more of a suit, a pair, or a draw-heavy board
# (two of a suit and a straight's worth of ranks, or more); "dry" otherwise.
TEXTURES = ("monotone", "paired", "wet", "dry")
# Positions in the order they act after the flop; heads-up the big blind acts first and the button ("BTN") last.
ACT_ORDER = ("SB", "BB", "UTG", "UTG+1", "UTG+2", "UTG+3", "UTG+4", "UTG+5", "LJ", "HJ", "CO", "BTN")
# What a hero's bets give away, flagged in `facts["hero"]["flags"]` (B4): a bluff bigger than the pot, a bet under a
# third of the pot on a draw-heavy board, and a second barrel of the same chips although the pot had grown.
SIZING_FLAGS = ("overbet_bluff", "small_on_wet", "same_chips_barrel")
SMALL_BET = 1 / 3
SAME_CHIPS = 0.1  # within this share of the first barrel
# The made hands the strong-fold check counts [JHU 8]: a set, or two pair using both hole cards.
STRONG_FOLDS = {"set", "two_pair"}
DRY_WETNESS = 1  # at most this wet: no flush draw beside a straight's worth of ranks, and no flush


def hand_facts(hand, with_equity=True):
    """The facts of a hand from `pokerstars.extract`: {"hand": Hand columns, "players": HandPlayer rows, "bets":
    HandBet rows}.

    With `with_equity`, a hand whose money went in before the river with every live hand shown also gets each live
    player's equity and expected result then (tracker.parsing.equity.all_in).
    """
    walk = _Walk(hand)
    for event in hand["events"]:
        walk.apply(event)
    players = walk.player_rows(equity.all_in(hand) if with_equity else None)
    return {"hand": walk.hand_columns(), "players": players, "bets": walk.bet_rows()}


def strength(made, drawing=(), nuts=False):
    """How strong a hand after the flop is, for sizing tells (B4): the nuts, strong, weak, a draw, or nothing."""
    if made in STRONG:
        return "nuts" if nuts else "strong"
    if made in SHOWDOWN_VALUE:
        return "weak"
    if STRONG_DRAWS & set(drawing):
        return "draw"
    return "nothing"


def texture_class(texture):
    """A board's texture as one of TEXTURES: monotone, paired, wet or dry."""
    if not texture:
        return ""
    if texture["suited"] >= 3:
        return "monotone"
    if texture["paired"]:
        return "paired"
    return "wet" if texture["wetness"] >= 2 else "dry"


class _Player:
    def __init__(self, row):
        self.name = row["name"]
        self.seat = row["seat"]
        self.position = row["position"]
        self.start = row["stack"]
        self.stack = row["stack"]
        self.cards = row["cards"]
        self.won = row["won"]
        self.net = row["net"]
        self.bet = 0  # in front of the player on this street
        self.folded = False
        self.all_in_street = None
        self.acted = False  # has made a decision before the flop
        self.voluntary = False  # has called or raised before the flop
        self.raised = False  # has raised before the flop
        self.saw_flop = False
        self.showdown = False
        self.situation = ""
        self.first_action = ""
        self.counts = dict.fromkeys(STATS, (0, 0))
        self.actions = {street: Counter() for street in ("preflop", *POSTFLOP)}
        self.checked_on = set()  # streets on which the player has checked
        self.check_raise_chances = set()
        self.sizes = []  # each bet and raise: [street, chips put in ÷ the pot before it]
        # Raises before the flop, for the discipline checks (hands.leaks): an open, the first raise, over any
        # limpers, raised to so many big blinds; a 3-bet, so many times the raise it re-raised, with that raise's
        # callers; and whether the player's first raise put them all-in.
        self.open_bb = None
        self.open_limpers = None
        self.three_bet_x = None
        self.three_bet_callers = None
        self.first_raise_all_in = None
        # The leak checks after the flop (hands.leaks, B5): facing a bet with a set or two pair on a dry, unpaired
        # board, and folding; checked to in position on the river, and checking back.
        self.strong_fold = [0, 0]
        self.river_checked_to = False
        self.checked_back = False

    def chance(self, stat, did):
        could, done = self.counts[stat]
        self.counts[stat] = (could + 1, done + bool(did))


class _Walk:
    """The table as the events go by, and what each player's decisions faced."""

    def __init__(self, hand):
        self.hand = hand
        self.bb = hand["big_blind"] or 1
        self.players = {row["name"]: _Player(row) for row in hand["players"]}
        self.pot = 0  # in the middle, without the bets still in front of the players
        self.street = "preflop"
        self.raisers = []  # who made each raise before the flop, the open first
        self.callers = 0  # calls since the last raise; before one, limps
        self.stealer = None  # the opener, when the open was a steal
        self.limped = False
        self.aggressors = {}  # street -> who made its last bet or raise
        self.raises_here = 0  # bets and raises on this street
        self.cbettor = None  # who c-bet this street, while the c-bet stands unraised
        self.acted_here = set()
        self.streets = {}
        self.hero_spr = None
        self.board = []
        self.bets = []  # every bet and raise, as HandBet rows
        self.answering = None  # the last bet or raise of this street, while the others answer it
        self.cbet_now = False  # the move being made is a c-bet
        self.lines = {}  # street -> how the hero played it

    def apply(self, event):
        kind = event["type"]
        player = self.players.get(event.get("player"))
        amount = event.get("amount", 0)
        if kind == "street":
            self.new_street(event)
        elif kind == "post":
            player.stack -= amount
            player.bet += amount - event.get("dead", 0)
            self.pot += event.get("dead", 0)
            if event.get("all_in"):
                player.all_in_street = player.all_in_street or "preflop"
        elif kind in MOVES:
            self.cbet_now = False
            (self.preflop if self.street == "preflop" else self.postflop)(player, kind)
            self.answer(player, kind)
            self.move(player, kind, amount, event.get("all_in", False))
        elif kind == "return":
            back = min(amount, player.bet)
            player.bet -= back
            self.pot -= amount - back
            player.stack += amount

    def top(self):
        return max(player.bet for player in self.players.values())

    def preflop(self, player, kind):
        """Counts the chances the player's decision before the flop was."""
        to_call = self.top() - player.bet
        can_raise = player.stack > to_call
        raises = len(self.raisers)
        raising = kind in AGGRESSIVE
        if not player.acted:
            player.acted = True
            player.situation = _situation(raises, self.callers)
            player.first_action = "raise" if raising else kind
            if raises == 0 and self.callers == 0:
                player.chance("rfi", raising)
                if player.position in STEAL_POSITIONS:
                    player.chance("steal", raising)
            if self.stealer and raises == 1 and self.callers == 0 and player.position in ("SB", "BB"):
                player.chance("fold_to_steal", kind == "fold")
                player.chance("call_vs_steal", kind == "call")
                player.chance("three_bet_vs_steal", raising)
                if player.position == "BB":
                    player.chance("bb_defend", kind != "fold")
        if raises == 0 and to_call > 0:
            player.chance("limp", kind == "call")
        if raises and not player.voluntary:
            player.chance("cold_call", kind == "call")
        if raises == 1 and self.raisers[-1] != player.name and can_raise:
            player.chance("three_bet", raising)
            if self.callers and not player.voluntary:
                player.chance("squeeze", raising)
        if raises == 2 and self.raisers[0] == player.name:
            player.chance("fold_to_three_bet", kind == "fold")
        if raises == 2 and self.raisers[-1] != player.name and can_raise:
            player.chance("four_bet", raising)

    def postflop(self, player, kind):
        """Counts the chances the player's decision after the flop was."""
        street = self.street
        raising = kind in AGGRESSIVE
        opener = self.raisers[-1] if self.raisers else None  # the preflop aggressor
        line = self.lines.get(street) if player.name == self.hand["hero"] else None
        if self.top() == player.bet:  # nothing to call
            if player.name == opener and self.cbet_chance(player, street):
                player.chance(f"cbet_{street}", raising)
                if raising:
                    self.cbettor = player.name
                    self.cbet_now = True
            if street == "flop" and opener and player.name != opener and opener not in self.acted_here:
                aggressor = self.players[opener]
                if not aggressor.folded and not aggressor.all_in_street:  # they could still have bet
                    player.chance("donk_flop", raising)
            if kind == "check":
                player.checked_on.add(street)
            if street == "river" and self.checked_to_last(player):
                player.river_checked_to = True
                player.checked_back = kind == "check"
            if line and line["first"] is None and line["faced"] is None:
                line["first"] = kind
        else:
            if self.cbettor and self.raises_here == 1 and player.name != self.cbettor:
                player.chance(f"fold_to_cbet_{street}", kind == "fold")
            if street in player.checked_on and street not in player.check_raise_chances:
                player.check_raise_chances.add(street)
                player.chance("check_raise", kind == "raise")
            if len(player.cards) == 2 and self.strong_on_dry_board(player):
                player.strong_fold = [1, int(player.strong_fold[1] or kind == "fold")]
            if line and line["faced"] is None:
                line["faced"] = kind

    def checked_to_last(self, player):
        """Whether everyone else still able to bet has checked this street, so the player acts last, in position."""
        others = [o for o in self.players.values() if o is not player and not o.folded and not o.all_in_street]
        return bool(others) and self.raises_here == 0 and all(o.name in self.acted_here for o in others)

    def strong_on_dry_board(self, player):
        """Whether a hold'em player holds a set, or two pair with both cards, on a dry board with no pair [JHU 8]."""
        texture = board_texture(self.board)
        if not texture or texture["paired"] or texture["wetness"] > DRY_WETNESS:
            return False
        return made_hand(player.cards, self.board) in STRONG_FOLDS

    def answer(self, player, kind):
        """Notes how the bet or raise being answered went: called or raised, and what the hero said to it."""
        bet = self.answering
        if bet is None or bet["name"] == player.name:
            return
        if kind == "raise":
            bet["outcome"] = "raised"
        elif kind == "call" and bet["outcome"] == "folded":
            bet["outcome"] = "called"
        if player.name == self.hand["hero"] and not bet["hero_response"] and kind in ("fold", "call", "raise"):
            bet["hero_response"] = kind

    def cbet_chance(self, player, street):
        """Whether betting first on `street` is a continuation bet: on the flop, or after one that went unraised."""
        if street == "flop":
            return True
        previous = POSTFLOP[POSTFLOP.index(street) - 1]
        return player.counts[f"cbet_{previous}"][1] > 0 and self.aggressors.get(previous) == player.name

    def move(self, player, kind, amount, all_in):
        """Puts the player's chips in and moves the betting on."""
        raising = kind in AGGRESSIVE
        faced = self.top()  # the bet to match, before this move
        player.actions[self.street][_ACTION_COUNT[kind]] += 1
        if raising:
            before = self.pot + sum(other.bet for other in self.players.values())
            player.sizes.append([self.street, round(amount / before, 3) if before else None])
            self.record_bet(player, kind, amount, before, all_in)
        player.stack -= amount
        player.bet += amount
        player.folded = player.folded or kind == "fold"
        if all_in:
            player.all_in_street = player.all_in_street or self.street
        self.acted_here.add(player.name)
        if self.street == "preflop":
            player.voluntary = player.voluntary or kind in ("call", "bet", "raise")
            if raising:
                self.preflop_size(player, faced, all_in)
            player.raised = player.raised or raising
            if raising:
                if not self.raisers and self.callers == 0 and player.position in STEAL_POSITIONS:
                    self.stealer = player.name
                self.raisers.append(player.name)
                self.callers = 0
            elif kind == "call":
                self.callers += 1
                self.limped = self.limped or not self.raisers
        if raising:
            self.raises_here += 1
            self.aggressors[self.street] = player.name

    def record_bet(self, player, kind, amount, before, all_in):
        """Lists a bet or raise: its size, what the player held if their cards are known, and how it went."""
        made, held, wetness = "", "", None
        if self.street in POSTFLOP:
            wetness = board_texture(self.board)["wetness"]
            if player.cards:
                made = made_hand(player.cards, self.board)
                holdem = len(player.cards) == 2
                drawing = draws(player.cards, self.board) if holdem else []
                nuts = holdem and made in _NUT_CANDIDATES and equity.is_nuts(player.cards, self.board)
                held = strength(made, drawing, nuts)
        bet = {
            "seat": player.seat,
            "name": player.name,
            "street": self.street,
            "order": len(self.bets),
            "kind": kind,
            "amount_bb": round(amount / self.bb, 3),
            "pot_bb": round(before / self.bb, 3),
            "size": round(amount / before, 3) if before else None,
            "to_bb": round((player.bet + amount) / self.bb, 3),
            "opponents": sum(1 for other in self.players.values() if other is not player and not other.folded),
            "all_in": all_in,
            "cbet": self.cbet_now,
            "made": made,
            "strength": held,
            "wetness": wetness,
            "outcome": "folded",  # until someone calls or raises it
            "hero_response": "",
        }
        self.bets.append(bet)
        self.answering = bet
        line = self.lines.get(self.street) if player.name == self.hand["hero"] else None
        if line and "bet" not in line:
            line["bet"] = bet

    def preflop_size(self, player, faced, all_in):
        """Notes the size of the player's raise before the flop, made to `player.bet` over a bet of `faced`."""
        if not player.raised:
            player.first_raise_all_in = all_in
        if not self.raisers:
            player.open_bb = round(player.bet / self.bb, 3)
            player.open_limpers = self.callers
        elif len(self.raisers) == 1 and faced:
            player.three_bet_x = round(player.bet / faced, 3)
            player.three_bet_callers = self.callers

    def new_street(self, event):
        for player in self.players.values():
            self.pot += player.bet
            player.bet = 0
        self.street = event["street"]
        self.raises_here = 0
        self.cbettor = None
        self.answering = None
        self.acted_here = set()
        self.board = event.get("board", self.board)
        alive = [player for player in self.players.values() if not player.folded]
        if self.street in POSTFLOP:
            stacks = sorted(player.stack for player in alive)
            board = event.get("board", [])
            hero = self.players.get(self.hand["hero"])
            if hero in alive:
                self.lines[self.street] = self.line(hero, alive, board)
            self.streets[self.street] = {
                "pot_bb": round(self.pot / self.bb, 2),
                "players": len(alive),
                # The most that can still go in: the second-biggest stack still in.
                "effective_bb": round(stacks[-2] / self.bb, 2) if len(stacks) > 1 else 0,
                "texture": board_texture(board),
            }
            if self.street == "flop":
                for player in alive:
                    player.saw_flop = True
                hero = self.players.get(self.hand["hero"])
                if hero in alive and self.pot:
                    # The hero's own: their stack, or the most the biggest stack against them can match.
                    most = max((player.stack for player in alive if player is not hero), default=0)
                    self.hero_spr = round(min(hero.stack, most) / self.pot, 2)
        elif self.street == "showdown":
            for player in alive:
                player.showdown = True

    def line(self, hero, alive, board):
        """How the hero comes to a street after the flop: their part before the flop (raised, called, or limped
        with no raise), whether they act last (null when nobody else can act), the players and the board's texture.
        Their first move with nothing to call, their answer to the first bet they face, and what came of their first
        bet are added as the street goes."""
        if not self.raisers:
            role = "limped"
        else:
            role = "raised" if self.raisers[-1] == hero.name else "called"
        order = {position: i for i, position in enumerate(ACT_ORDER)}
        others = [player for player in alive if player is not hero and not player.all_in_street]
        last = all(order.get(hero.position, 0) > order.get(other.position, 0) for other in others)
        return {
            "role": role,
            "ip": last if others else None,
            "players": len(alive),
            "texture": texture_class(board_texture(board)),
            "first": None,
            "faced": None,
        }

    def hero_lines(self):
        """The hero's lines by street, each with what came of their first bet on it: folded, called or raised."""
        lines = {}
        for street, line in self.lines.items():
            bet = line.get("bet")
            kept = {key: value for key, value in line.items() if key != "bet"}
            lines[street] = {**kept, "outcome": bet and bet["outcome"]}
        return lines

    def sizing_flags(self, hero):
        """What the hero's bets after the flop give away (SIZING_FLAGS)."""
        mine = [bet for bet in self.bets if bet["name"] == hero.name and bet["street"] in POSTFLOP]
        flags = set()
        for bet in mine:
            if bet["size"] is not None and bet["size"] > 1 and bet["strength"] == "nothing":
                flags.add("overbet_bluff")
            if bet["kind"] == "bet" and bet["size"] is not None and bet["size"] < SMALL_BET and bet["wetness"] >= 2:
                flags.add("small_on_wet")
        barrels = {bet["street"]: bet for bet in mine if bet["kind"] == "bet"}
        for first, second in zip(POSTFLOP, POSTFLOP[1:]):
            one, two = barrels.get(first), barrels.get(second)
            if one and two and abs(two["amount_bb"] - one["amount_bb"]) <= SAME_CHIPS * one["amount_bb"]:
                if two["pot_bb"] > one["pot_bb"]:
                    flags.add("same_chips_barrel")
        return [flag for flag in SIZING_FLAGS if flag in flags]

    def pot_type(self):
        if self.raisers:
            return ("single_raised", "3bet", "4bet+")[min(len(self.raisers), 3) - 1]
        return "limped" if self.limped else "walk"

    def hand_columns(self):
        hand = self.hand
        hero = self.players.get(hand["hero"])
        flop = self.streets.get("flop")
        facts = {
            "preflop_aggressor": self.raisers[-1] if self.raisers else None,
            "players_at_flop": flop["players"] if flop else 0,
            "streets": self.streets,
            "spr": round(flop["effective_bb"] / flop["pot_bb"], 2) if flop and flop["pot_bb"] else None,
        }
        tournament = hand.get("tournament")
        if tournament:
            facts["tournament"] = tournament
        columns = {
            "players_dealt": len(self.players),
            "pot_type": self.pot_type(),
            "hero_combo": "",
            "hero_situation": "",
            "hero_first_action": "",
            "effective_bb": None,
            "hero_m": None,
            "level": tournament["level"] if tournament else None,
            "facts": facts,
        }
        if hero is None:
            return columns
        others = [player.start for player in self.players.values() if player is not hero]
        holdem = len(hero.cards) == 2
        columns.update(
            hero_combo=combo(hero.cards) if holdem else "",
            hero_situation=hero.situation,
            hero_first_action=hero.first_action,
            effective_bb=round(min(hero.start, max(others, default=0)) / self.bb, 2),
            hero_m=self.m(hero),
        )
        facts["hero"] = {
            "group": hand_group(hero.cards) if holdem else "",
            "spr": self.hero_spr,
            "made": {},
            "draws": {},
        }
        board = hand["board"]
        if hero.cards:
            for street, cards in zip(POSTFLOP, (3, 4, 5), strict=True):
                if street in self.streets and len(board) >= cards and not _folded_before(hero, street):
                    facts["hero"]["made"][street] = made_hand(hero.cards, board[:cards])
                    if holdem and cards < 5:
                        facts["hero"]["draws"][street] = draws(hero.cards, board[:cards])
        made = facts["hero"]["made"]
        # What the hero ended with: their made hand on the last street they saw.
        facts["hero"]["final"] = next((made[street] for street in reversed(POSTFLOP) if street in made), None)
        facts["hero"]["lines"] = self.hero_lines()
        facts["hero"]["flags"] = self.sizing_flags(hero)
        return columns

    def m(self, player):
        """Harrington's M in a tournament: the stack ÷ (small blind + big blind + this hand's antes)."""
        if not self.hand["tournament_id"]:
            return None
        antes = sum(event["amount"] for event in self.hand["events"] if event.get("blind") == "ante")
        return round(player.start / (self.hand["small_blind"] + self.hand["big_blind"] + antes), 2)

    def player_rows(self, all_in=None):
        """Every player's row; `all_in` holds the live players' equity when the money went in, if it was known."""
        # The house rakes every pot at the same rate, so a player expects that much less of what they win.
        kept = 1 - self.hand.get("rake", 0) / self.hand["total_pot"] if self.hand.get("total_pot") else 1
        rows = []
        for player in self.players.values():
            ev = (all_in or {}).get(player.name)
            if player.acted:
                player.counts["vpip"] = (1, int(player.voluntary))
                player.counts["pfr"] = (1, int(player.raised))
            player.counts["saw_flop"] = (1, int(player.saw_flop))
            player.counts["went_to_showdown"] = (int(player.saw_flop), int(player.showdown))
            player.counts["won_at_showdown"] = (int(player.showdown), int(player.showdown and player.won > 0))
            chances = {}
            for stat, (could, did) in player.counts.items():
                chances[f"{stat}_could"], chances[f"{stat}_did"] = could, did
            after_flop = sum((player.actions[street] for street in POSTFLOP), Counter())
            rows.append(
                {
                    "seat": player.seat,
                    "name": player.name,
                    "position": player.position,
                    "stack_bb": round(player.start / self.bb, 2),
                    "cards": player.cards,
                    "situation": player.situation,
                    "first_action": player.first_action,
                    **chances,
                    **{f"postflop_{action}": after_flop[action] for action in POSTFLOP_ACTIONS},
                    "invested_bb": (player.won - player.net) / self.bb,
                    "net_bb": player.net / self.bb,
                    "allin_street": player.all_in_street or "",
                    "open_bb": player.open_bb,
                    "open_limpers": player.open_limpers,
                    "three_bet_x": player.three_bet_x,
                    "three_bet_callers": player.three_bet_callers,
                    "first_raise_all_in": player.first_raise_all_in,
                    "strong_fold_could": player.strong_fold[0],
                    "strong_fold_did": player.strong_fold[1],
                    # Checked back the river in position, then won the showdown: value missed [JHU 9].
                    "thin_value_could": int(player.river_checked_to),
                    "thin_value_did": int(player.checked_back and player.showdown and player.won > 0),
                    "allin_equity": None if ev is None else round(ev["equity"], 4),
                    "ev_net_bb": None if ev is None else (ev["expected"] * kept - ev["invested"]) / self.bb,
                    "extra": {
                        "actions": {street: dict(counts) for street, counts in player.actions.items() if counts},
                        "sizes": player.sizes,
                        "m": self.m(player),
                    },
                }
            )
        return rows


    def bet_rows(self):
        """Every bet and raise in the order made, as HandBet rows."""
        return list(self.bets)


def _situation(raises, callers):
    """What a player's first decision before the flop faced."""
    if raises == 0:
        return "limped" if callers else "unopened"
    return ("raised", "3bet", "4bet+")[min(raises, 3) - 1]


def _folded_before(player, street):
    """Whether the player folded before `street` was dealt, from their action counts."""
    streets = ("preflop", *POSTFLOP)
    return any(player.actions[earlier]["folds"] for earlier in streets[: streets.index(street)])


def _rank(card):
    return RANKS.index(card[0]) + 2


def combo(cards):
    """Two hole cards as a starting hand: "AKs", "T9o", "88"."""
    high, low = sorted(cards, key=_rank, reverse=True)
    if high[0] == low[0]:
        return high[0] + low[0]
    return high[0] + low[0] + ("s" if high[1] == low[1] else "o")


def hand_group(cards):
    """The class of a hold'em starting hand, from the Johns Hopkins course [JHU 3; JHU 4]; "junk" if none."""
    name = combo(cards)
    ranks = name[:2]
    high, low = _rank(name[0]), _rank(name[1])
    if ranks in _PREMIUM:
        return "premium"
    if high == low:
        return "big_pair" if high >= 10 else "medium_pair" if high >= 7 else "small_pair"
    if ranks == "AQ":
        return "big_ace"
    if name.endswith("s") and high - low == 1 and 5 <= high <= 11:  # 54s to JTs
        return "suited_connector"
    if ranks in _TROUBLE:
        return "trouble"
    if name[0] == "A":
        return "weak_ace"
    return "junk"


def made_hand(hole, board):
    """What the hero holds on a board: PokerKit's category, refined for hold'em's pairs and trips.

    Hold'em: set, trips, two_pair (both hole cards), overpair, pocket_pair (between the board's cards),
    underpair, top_pair_top_kicker, top_pair, second_pair, bottom_pair, overcards or high_card; and
    straight or better as PokerKit names them. Omaha: PokerKit's category alone.
    """
    hand_type = StandardHighHand if len(hole) == 2 else OmahaHoldemHand
    label = hand_type.from_game("".join(hole), "".join(board)).entry.label.name.lower()
    if len(hole) != 2 or label not in ("high_card", "one_pair", "two_pair", "three_of_a_kind"):
        return label
    holes = sorted((_rank(card) for card in hole), reverse=True)
    counts = Counter(_rank(card) for card in board)
    boards = sorted(counts, reverse=True)  # the board's ranks, high first
    if label == "three_of_a_kind":
        if holes[0] == holes[1]:
            return "set"
        if any(counts[rank] >= 2 for rank in holes):
            return "trips"
    if label == "two_pair" and holes[0] != holes[1] and all(rank in counts for rank in holes):
        return "two_pair"
    # Otherwise the hero's own pair, if any: a pocket pair, or a hole card that pairs the board.
    if holes[0] == holes[1]:
        if holes[0] > boards[0]:
            return "overpair"
        return "underpair" if holes[0] < boards[-1] else "pocket_pair"
    for rank in holes:
        if rank in counts:
            if rank != boards[0]:
                return "second_pair" if rank == boards[1] else "bottom_pair"
            kicker = holes[1] if rank == holes[0] else holes[0]
            best = max(other for other in range(2, 15) if other != rank and other not in counts)
            return "top_pair_top_kicker" if kicker == best else "top_pair"
    return "overcards" if holes[1] > boards[0] else "high_card"


def draws(hole, board):
    """The hold'em draws the hero's cards make on a flop or turn, e.g. ["nut_flush_draw", "gutshot"].

    Flush draws: nut_flush_draw (the hero holds the best card of the suit left
    off the board), flush_draw, and on the flop backdoor_flush_draw. Straight
    draws: open_ended, double_gutshot, gutshot. A draw counts only if a hole
    card is part of it, and none is counted once the hero has a straight or
    better.
    """
    if len(board) >= 5:  # nothing left to draw to
        return []
    label = StandardHighHand.from_game("".join(hole), "".join(board)).entry.label.name.lower()
    if label not in ("high_card", "one_pair", "two_pair", "three_of_a_kind"):
        return []
    found = []
    cards = [*hole, *board]
    for suit in "cdhs":
        mine = [card for card in hole if card[1] == suit]
        suited = sum(card[1] == suit for card in cards)
        if mine and suited == 4:
            nut = max((rank for rank in RANKS if rank + suit not in board), key=RANKS.index)
            found.append("nut_flush_draw" if any(card[0] == nut for card in mine) else "flush_draw")
        elif mine and suited == 3 and len(board) == 3:
            found.append("backdoor_flush_draw")

    def ranks(of):  # an ace plays high and low
        values = {_rank(card) for card in of}
        return values | {1} if 14 in values else values

    present, mine, on_board = ranks(cards), ranks(hole), ranks(board)
    outs = set()
    for low in range(1, 11):
        window = set(range(low, low + 5))
        missing = window - present
        held = window - missing
        if len(missing) == 1 and held & mine and not held <= on_board:
            outs |= missing
    open_ended = any(
        low - 1 in outs and low + 4 in outs and set(range(low, low + 4)) <= present for low in range(2, 11)
    )
    if len(outs) >= 2:
        found.append("open_ended" if open_ended else "double_gutshot")
    elif outs:
        found.append("gutshot")
    return found


def board_texture(board):
    """How a board reads: paired or not, its commonest suit's count, whether a straight fits, its top card, its wetness.

    `suited` is 1 on a rainbow flop, 2 on a two-tone one, 3 on a monotone one.
    `wetness` runs from 0 (dry) to 3: one for a flush draw, two for a possible
    flush, and one when three of its ranks fit in a straight.
    """
    if not board:
        return {}
    suited = max(Counter(card[1] for card in board).values())
    values = {_rank(card) for card in board}
    values |= {1} if 14 in values else set()
    straight = any(len(values & set(range(low, low + 5))) >= 3 for low in range(1, 11))
    return {
        "paired": len({card[0] for card in board}) < len(board),
        "suited": suited,
        "straight_possible": straight,
        "high_card": max((card[0] for card in board), key=RANKS.index),
        "wetness": (2 if suited >= 3 else 1 if suited == 2 else 0) + int(straight),
    }
