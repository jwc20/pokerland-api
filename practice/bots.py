"""The bots at a practice table: one of four styles, plus a leak to find; or a profile, at a table of any size.

The styles are the four of the style quadrant and of the synthetic-hand generator (dev-tools/gen_hands.py):
tight-aggressive, loose-aggressive, the calling station and the rock [MIT 1]. A bot decides from what its own
seat sees, the context practice.spots works out for it, and the moves PokerKit allows: how strong its cards are
(Chen's score before the flop, the made hand and draws after it), the price, and its style's habits.

A leak is one exaggerated habit layered on top (pokerland-practice-mode-additional.md, 6.3), so a player can
find it in twenty hands and adjust: it never folds a pair, folds to any second bet, bets big with weak hands,
raises only with a very strong hand, raises every button, or never bluffs the river. The coached match's bots are
these, heads-up.

**Profiles** play a table of any size (pokerland-practice-mode.md, 7.2, Play it out). A profile is a player's habits
as the statistics the app counts (tracker.parsing.facts.STATS): how often they raise first in from each seat, limp,
3-bet, call a raise, 4-bet, fold to a 3-bet and defend the big blind before the flop, and how often they c-bet, fold
to one and bet or raise at all after it. Before the flop a profile bot plays the top share of hands each rate says,
by the ranking hands.ranges keeps; after it, its hand's class and the price, at the rates. The four styles have
profiles, and so can a real opponent: `calibrated` draws theirs from their statistics in the user's hands (FND-6),
towards a typical player's while their sample is small.

Django-free, like practice.table.
"""

from hands import ranges
from practice.rules import chen

STYLES = {
    "tag": "Tight-aggressive",
    "lag": "Loose-aggressive",
    "station": "Calling station",
    "rock": "Rock",
}
LEAKS = {
    "never_folds_pair": "Never folds a pair",
    "folds_to_second_bet": "Folds to any second bet",
    "bets_big_weak": "Bets big with weak hands",
    "raises_only_nuts": "Raises only with a very strong hand",
    "raises_every_button": "Raises every button",
    "never_bluffs_river": "Never bluffs the river",
}

# Each style's habits, heads-up. Chen scores to open the button, defend the big blind and 3-bet; how often it bets
# when checked to with nothing, c-bets, calls a bet with nothing or a draw, and raises a bet with a strong hand.
HABITS = {
    "tag": {"open": 4, "defend": 5, "three_bet": 11, "bluff": 0.25, "cbet": 0.7, "float": 0.25, "raise": 0.3},
    "lag": {"open": 1, "defend": 3, "three_bet": 9, "bluff": 0.45, "cbet": 0.85, "float": 0.35, "raise": 0.45},
    "station": {"open": 9, "defend": 0, "three_bet": 14, "bluff": 0.08, "cbet": 0.35, "float": 0.6, "raise": 0.05},
    "rock": {"open": 7, "defend": 8, "three_bet": 13, "bluff": 0.05, "cbet": 0.5, "float": 0.02, "raise": 0.2},
}
VERY_STRONG = {"two_pair", "set", "trips", "straight", "flush", "full_house", "four_of_a_kind", "straight_flush"}


def decide(context, legal, style, leak, rng):
    """The bot's move: (action, amount), the amount being the total a bet or raise makes its bet, else None.

    `context` is practice.spots' for the bot's seat, `legal` practice.table's, `rng` a random.Random.
    """
    habits = HABITS[style]
    if context["street"] == "preflop":
        action, size = _preflop(context, legal, style, leak, habits, rng)
    else:
        action, size = _postflop(context, legal, style, leak, habits, rng)
    return _legalise(action, size, context, legal)


def _preflop(context, legal, style, leak, habits, rng):
    score = chen(context["cards"])
    to_call = legal["to_call"]
    raised = context["situation"] not in ("unopened", "limped")
    if not raised:
        if context["hero_position"] == "BTN" and to_call > 0:  # first in, on the button
            if leak == "raises_every_button" or score >= habits["open"] + rng.uniform(-1.5, 1.5):
                return "raise", ("bb", 2.5)
            # A station limps where the others fold.
            return ("call", None) if style == "station" else ("fold", None)
        # In the big blind after a limp: raise the good hands, else see the flop.
        if score >= habits["three_bet"] - 2 and leak != "raises_only_nuts":
            return "raise", ("bb", 3.5)
        return "check", None
    facing = context["facing_bb"] or 0
    if context["facing_all_in"] or to_call >= legal["stack"]:
        return ("call", None) if score >= _shove_calling_score(facing, style) else ("fold", None)
    three_bet = habits["three_bet"] if leak != "raises_only_nuts" else 15
    if legal["can_raise"] and score >= three_bet + rng.uniform(-1, 1) and context["situation"] == "raised":
        return "raise", ("times", 3)
    if leak == "folds_to_second_bet" and context["situation"] != "raised" and score < 14:
        return "fold", None
    # Defend wider against a small raise: the price is better.
    needed = context["equity_needed"] or 0.5
    defend = habits["defend"] + (needed - 0.3) * 10
    if context["situation"] != "raised":  # facing a 3-bet or more
        defend += 4
    return ("call", None) if score >= defend else ("fold", None)


def _shove_calling_score(facing_bb, style):
    """The Chen score a bot calls an all-in with: wider the shorter it is, and wider for a station."""
    base = 10 if facing_bb > 20 else 8 if facing_bb > 12 else 6
    return base - (3 if style == "station" else 0) + (2 if style == "rock" else 0)


def _postflop(context, legal, style, leak, habits, rng):
    held = context["hand_class"]
    made = context["made"]
    very_strong = made in VERY_STRONG
    river = context["street"] == "river"
    if context["facing"] == "none":
        bluff_allowed = not (river and leak == "never_bluffs_river")
        if held == "strong":
            bet = rng.random() < (0.85 if very_strong else 0.7)
        elif held == "draw":
            bet = rng.random() < habits["bluff"] + 0.15
        elif held == "showdown_value":
            bet = rng.random() < habits["bluff"] / 2
        else:
            cbet = context["street"] == "flop" and context["aggressor"] == "hero"
            bet = bluff_allowed and rng.random() < (habits["cbet"] if cbet else habits["bluff"])
        if not bet:
            return "check", None
        return "bet", ("pot", _bet_size(held, very_strong, leak, rng))
    # Facing a bet or a raise.
    if leak == "folds_to_second_bet" and context["bets_faced"] >= 1 and not very_strong:
        return "fold", None
    if leak == "never_folds_pair" and context["pair_or_better"]:
        return _raise_or_call(very_strong, legal, leak, habits, rng)
    if held == "strong":
        return _raise_or_call(very_strong, legal, leak, habits, rng)
    needed = context["equity_needed"] or 0
    if held == "draw":
        return ("call", None) if needed <= 0.33 or rng.random() < habits["float"] else ("fold", None)
    if held == "showdown_value":
        willing = 0.3 + habits["float"] * 0.4
        return ("call", None) if needed <= willing else ("fold", None)
    return ("call", None) if rng.random() < habits["float"] * (1 - needed) else ("fold", None)


def _raise_or_call(very_strong, legal, leak, habits, rng):
    if not legal["can_raise"]:
        return "call", None
    if leak == "raises_only_nuts":
        return ("raise", ("times", 3)) if very_strong else ("call", None)
    if rng.random() < habits["raise"] * (1.5 if very_strong else 0.6):
        return "raise", ("times", 3)
    return "call", None


def _bet_size(held, very_strong, leak, rng):
    """A bet's size as a share of the pot. One that bets big with weak hands sizes upside down."""
    if leak == "bets_big_weak":
        return rng.choice((1.0, 1.2)) if held in ("nothing", "draw", "showdown_value") else 0.33
    if very_strong:
        return rng.choice((0.5, 0.66, 0.75))
    return rng.choice((0.33, 0.5, 0.66))


def _legalise(action, size, context, legal):
    """The move as PokerKit takes it: a size turned into chips within the legal sizes; a check for a free fold."""
    if action == "fold" and legal["can_check"]:
        return "check", None
    if action == "check" and not legal["can_check"]:
        return "fold", None
    if action == "call" and legal["can_check"]:
        return "check", None
    if action in ("bet", "raise"):
        if not legal["can_raise"]:
            return ("check", None) if legal["can_check"] else ("call", None)
        unit, value = size
        if unit == "bb":
            to = value * context["big_blind"]
        elif unit == "times":
            to = value * (legal["bet"] + legal["to_call"])
        else:
            to = legal["bet"] + legal["to_call"] + value * (context["pot"] + legal["to_call"])
        to = int(min(legal["max_to"], max(legal["min_to"], round(to))))
        return legal["raise_kind"], to
    return action, None


# Profiles ------------------------------------------------------------------------------------------------------

# Seats by how a player opens from them: early, middle, the cutoff, the button and the small blind.
SEAT_GROUPS = {
    "UTG": "EP", "UTG+1": "EP", "UTG+2": "EP", "UTG+3": "EP", "UTG+4": "EP", "UTG+5": "EP",
    "LJ": "MP", "HJ": "MP",
    "CO": "CO", "BTN": "BTN", "SB": "SB",
}
# Each style's habits as a profile, in percent, near the synthetic hands' styles (dev-tools/gen_hands.py).
PROFILES = {
    "tag": {
        "rfi": {"EP": 14, "MP": 18, "CO": 27, "BTN": 42, "SB": 33},
        "limp": 2, "three_bet": 8, "cold_call": 10, "four_bet": 3, "fold_to_three_bet": 55, "bb_defend": 40,
        "cbet": 70, "fold_to_cbet": 45, "aggression": 45,
    },
    "lag": {
        "rfi": {"EP": 22, "MP": 28, "CO": 38, "BTN": 55, "SB": 45},
        "limp": 3, "three_bet": 14, "cold_call": 16, "four_bet": 6, "fold_to_three_bet": 40, "bb_defend": 55,
        "cbet": 80, "fold_to_cbet": 35, "aggression": 55,
    },
    "station": {
        "rfi": {"EP": 8, "MP": 10, "CO": 12, "BTN": 18, "SB": 15},
        "limp": 25, "three_bet": 2, "cold_call": 35, "four_bet": 1, "fold_to_three_bet": 30, "bb_defend": 70,
        "cbet": 40, "fold_to_cbet": 20, "aggression": 20,
    },
    "rock": {
        "rfi": {"EP": 7, "MP": 9, "CO": 12, "BTN": 20, "SB": 12},
        "limp": 3, "three_bet": 3, "cold_call": 6, "four_bet": 1.5, "fold_to_three_bet": 65, "bb_defend": 25,
        "cbet": 55, "fold_to_cbet": 60, "aggression": 30,
    },
}
# The statistics each rate in a profile is drawn from (tracker.parsing.facts.STATS).
PROFILE_STATS = {
    "limp": "limp",
    "three_bet": "three_bet",
    "cold_call": "cold_call",
    "four_bet": "four_bet",
    "fold_to_three_bet": "fold_to_three_bet",
    "bb_defend": "bb_defend",
    "cbet": "cbet_flop",
    "fold_to_cbet": "fold_to_cbet_flop",
}
PRIOR = 15  # chances' worth of a typical player's rate a player's own is drawn towards
HEADS_UP_OPENING = 1.8  # heads-up the button opens this much wider than at a full table, up to 95%


def calibrated(counters, seats, typical=None, prior=PRIOR):
    """A profile from a player's summed statistics (hands.models.Opponent.counters), each rate drawn towards
    `typical`'s by `prior` chances' worth of it. `seats` gives their raises first in by seat: {position: (did, could)}.
    """
    typical = typical or PROFILES["tag"]

    def drawn(did, could, towards):
        return round(100 * (did + prior * towards / 100) / (could + prior), 1)

    profile = {
        rate: drawn(counters.get(f"{stat}_did", 0), counters.get(f"{stat}_could", 0), typical[rate])
        for rate, stat in PROFILE_STATS.items()
    }
    # Raises first in from each kind of seat, towards the typical player's there scaled by their own rate overall.
    average = sum(typical["rfi"].values()) / len(typical["rfi"])
    overall = drawn(counters.get("rfi_did", 0), counters.get("rfi_could", 0), average)
    profile["rfi"] = {}
    for group, value in typical["rfi"].items():
        did = sum(found[0] for seat, found in seats.items() if SEAT_GROUPS.get(seat) == group)
        could = sum(found[1] for seat, found in seats.items() if SEAT_GROUPS.get(seat) == group)
        profile["rfi"][group] = drawn(did, could, min(95, value * overall / average))
    aggressive = counters.get("postflop_bets", 0) + counters.get("postflop_raises", 0)
    moves = aggressive + counters.get("postflop_calls", 0) + counters.get("postflop_folds", 0)
    profile["aggression"] = drawn(aggressive, moves, typical["aggression"])
    return profile


def play(context, legal, profile, rng):
    """A profile bot's move at a table of any size: (action, amount), as `decide` gives it."""
    if context["street"] == "preflop":
        action, size = _profile_preflop(context, legal, profile, rng)
    else:
        action, size = _profile_postflop(context, legal, profile, rng)
    return _legalise(action, size, context, legal)


def move(context, legal, seat, rng):
    """A bot seat's move: by its profile if it has one, else by its style and leak."""
    if seat.get("profile"):
        return play(context, legal, seat["profile"], rng)
    return decide(context, legal, seat["style"], seat.get("leak"), rng)


def opening(seat, profile, heads_up=False):
    """The share of hands, in percent, a profile raises first in with from a seat."""
    share = profile["rfi"].get(SEAT_GROUPS.get(seat, "MP"), profile["rfi"]["MP"])
    return min(95.0, share * HEADS_UP_OPENING) if heads_up else share


def _profile_preflop(context, legal, profile, rng):
    combo = ranges.combo_of(context["cards"])
    if combo is None:  # Omaha: profiles play hold'em
        return "fold", None
    rank = 100 * ranges.percentile(combo) + rng.uniform(-2, 2)  # 0 for the best hand; the noise mixes each edge
    situation, to_call, seat = context["situation"], legal["to_call"], context["hero_position"]
    if context["facing_all_in"] or (to_call and to_call >= legal["stack"]):
        return ("call", None) if rank < _all_in_calls(context, profile) else ("fold", None)
    if situation == "unopened":
        share = opening(seat, profile, context["heads_up"])
        if rank < share:
            return "raise", ("bb", 2.5 if context["heads_up"] else 3)
        return ("call", None) if to_call and rank < share + profile["limp"] else ("fold", None)
    if situation == "limped":
        share = opening(seat, profile)
        if not to_call:  # the big blind's option
            return ("raise", ("bb", 4 + context["callers"])) if rank < 1.5 * profile["three_bet"] else ("check", None)
        if rank < 0.6 * share:
            return "raise", ("bb", 4 + context["callers"])
        return ("call", None) if rank < share + profile["limp"] else ("fold", None)
    if situation == "raised":
        if rank < profile["three_bet"]:
            return "raise", ("times", 3 + context["callers"])
        # The big blind facing one raise defends at its own rate; anyone else calls at their cold-calling rate.
        defending = seat == "BB" and not context["callers"]
        calls = profile["bb_defend"] - profile["three_bet"] if defending else profile["cold_call"]
        return ("call", None) if rank < profile["three_bet"] + max(0.0, calls) else ("fold", None)
    if situation == "3bet":
        if "raise" in context["line"]:  # they opened and were re-raised
            if rank < profile["four_bet"]:
                return "raise", ("times", 2.5)
            kept = opening(seat, profile, context["heads_up"]) * (1 - profile["fold_to_three_bet"] / 100)
            return ("call", None) if rank < kept else ("fold", None)
        return ("call", None) if rank < profile["four_bet"] else ("fold", None)
    return ("call", None) if rank < 0.6 * profile["four_bet"] else ("fold", None)


def _all_in_calls(context, profile):
    """The share of hands a profile calls an all-in with: wider the shorter the shove, and the looser the player."""
    facing = context["facing_bb"] or 0
    base = 6 if facing > 20 else 12 if facing > 12 else 22
    tag = PROFILES["tag"]
    loose = (profile["three_bet"] + profile["cold_call"]) / (tag["three_bet"] + tag["cold_call"])
    return base * min(2.5, max(0.5, loose))


def _profile_postflop(context, legal, profile, rng):
    held, made = context["hand_class"], context["made"]
    very_strong = made in VERY_STRONG
    aggression = profile["aggression"] / 100
    others = max(1, context["players"] - 1)
    if context["facing"] == "none":
        continuing = context["street"] == "flop" and context["aggressor"] == "hero"
        if held == "strong":
            chance = max(0.5 + 0.4 * aggression, 0.75 if continuing else 0)
        elif continuing:
            chance = profile["cbet"] / 100 / (1 + 0.4 * (others - 1))
        elif held == "draw":
            chance = 0.6 * aggression
        elif held == "showdown_value":
            chance = 0.15 * aggression
        else:
            chance = 0.5 * aggression / others
        if rng.random() >= chance:
            return "check", None
        return "bet", ("pot", rng.choice((0.5, 0.66, 0.75)) if very_strong else rng.choice((0.33, 0.5, 0.66)))
    folds = profile["fold_to_cbet"] / 100
    needed = context["equity_needed"] or 0
    if held == "strong":
        if legal["can_raise"] and rng.random() < aggression * (0.6 if very_strong else 0.25):
            return "raise", ("times", 3)
        return "call", None
    if held == "draw":
        if legal["can_raise"] and rng.random() < 0.2 * aggression:
            return "raise", ("times", 3)
        return ("call", None) if needed <= 0.3 or rng.random() > folds else ("fold", None)
    if held == "showdown_value":
        return ("call", None) if rng.random() < (1 - folds) * (1.3 - needed) else ("fold", None)
    if legal["can_raise"] and rng.random() < 0.08 * aggression:  # a bluff-raise now and then
        return "raise", ("times", 3)
    return ("call", None) if rng.random() < (1 - folds) * 0.35 * (1 - needed) else ("fold", None)
