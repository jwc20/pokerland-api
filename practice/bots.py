"""The bots at a practice table: one of four styles, plus a leak to find.

The styles are the four of the style quadrant and of the synthetic-hand generator (dev-tools/gen_hands.py):
tight-aggressive, loose-aggressive, the calling station and the rock [MIT 1]. A bot decides from what its own
seat sees, the context practice.spots works out for it, and the moves PokerKit allows: how strong its cards are
(Chen's score before the flop, the made hand and draws after it), the price, and its style's habits.

A leak is one exaggerated habit layered on top (pokerland-practice-mode-additional.md, 6.3), so a player can
find it in twenty hands and adjust: it never folds a pair, folds to any second bet, bets big with weak hands,
raises only with a very strong hand, raises every button, or never bluffs the river.

Django-free, like practice.table.
"""

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
