"""The house playbooks: short, named, versioned lists of rule cards (pokerland-practice-mode-additional.md, 4.4).

A card says the rule, why, who it is for, its exceptions and its source, and carries the test practice.rules
runs: `when` (what the decision faced, from practice.spots), `unless` (spots it leaves out) and `then` (what to
do). A card's `kind` is "action" (what to do) or "sizing" (how much, once you bet). Adjustments are cards that a
read on the opponent unlocks (`read`), each for one kind of opponent.

A playbook is a preset, not the truth: the lecturers disagree on the defaults, so presets are named and
versioned. Change a card and raise the version: practice.models.Playbook keeps each version's cards as they were,
so matches played under an older one still read the same.

Sources: [GA m:ss] is Garrett Adelstein coaching Sodapoppin (https://www.youtube.com/watch?v=FCO42X2uIJg);
[MIT n] and [JHU n] are the lectures, numbered as in pokerland-feature-ideas.md.
"""

# The rule families. A player moves through the coach's stages one family at a time.
FAMILIES = {
    "button": "Button play",
    "out_of_position": "Out of position",
    "sizing": "Sizing",
    "showdown_value": "Showdown value and price",
    "stack_depth": "Stack depth and all-ins",
    "adjustments": "Adjustments",
}

# The reads that unlock adjustments, as the read card names them.
READS = {
    "doesnt_fold": "An opponent who doesn't fold",
    "unknown": "An opponent you can't read yet",
    "big_bets_weak": "An opponent whose big bets have shown up weak",
}

POSTFLOP = ["flop", "turn", "river"]

STARTER = {
    "key": "starter-heads-up",
    "name": "Starter heads-up playbook",
    "version": 1,
    "game": "Hold'em No Limit",
    "format": "heads_up",
    "description": (
        "Ten defaults you can apply in eight seconds, from a coach's first session with a new player, and three "
        "adjustments a read unlocks. Rules 1 and 10 are training wheels, to be swapped for reference ranges "
        "once your preflop and push-or-fold skills are solid."
    ),
    "rules": [
        {
            "id": "button_raise_every_hand",
            "number": 1,
            "family": "button",
            "kind": "action",
            "rule": "On the button, raise first in with every hand, to one size",
            "why": "You act last on every later street, and one rule is easier than sorting hands you can't yet sort.",
            "scope": "heads_up",
            "simplification": True,
            "exceptions": "Ten big blinds or less: move in or fold instead [JHU 6].",
            "when": {"street": "preflop", "heads_up": True, "hero_position": "BTN", "situation": "unopened"},
            "unless": ["short"],
            "then": {"action": "raise", "to_bb": 2.5},
            "source": ["GA 2:53", "GA 3:33", "MIT 3", "JHU 6"],
        },
        {
            "id": "oop_check_to_raiser",
            "number": 2,
            "family": "out_of_position",
            "kind": "action",
            "rule": "Out of position after calling a preflop raise, check the flop",
            "why": "The raiser usually bets. Checking every hand tells them nothing about yours.",
            "scope": "anyone",
            "exceptions": "More than one opponent.",
            "when": {"street": "flop", "position": "out", "preflop": "called_raise", "facing": "none"},
            "unless": ["multiway"],
            "then": {"action": "check"},
            "source": ["GA 0:35", "GA 10:26", "JHU 5", "JHU 9"],
        },
        {
            "id": "oop_check_after_check_call",
            "number": 3,
            "family": "out_of_position",
            "kind": "action",
            "rule": "After you check and call out of position, check the next street",
            "why": "The bettor usually bets again. Checking every hand tells them nothing about yours.",
            "scope": "anyone",
            "exceptions": "More than one opponent.",
            "when": {"street": ["turn", "river"], "position": "out", "previous": "check_call", "facing": "none"},
            "unless": ["multiway"],
            "then": {"action": "check"},
            "source": ["GA 5:51", "GA 14:07", "GA 16:06"],
        },
        {
            "id": "cbet_half_pot",
            "number": 4,
            "family": "sizing",
            "kind": "sizing",
            "rule": "When you raised preflop and bet the flop, bet half the pot",
            "why": "One size for every hand gives nothing away, and half the pot denies most draws their price.",
            "scope": "anyone",
            "exceptions": "More than one opponent.",
            "when": {"street": "flop", "preflop": "raised", "facing": "none"},
            "unless": ["multiway"],
            "then": {"action": "bet", "size": 0.5},
            "source": ["GA 8:30", "JHU 4", "MIT 8"],
        },
        {
            "id": "half_pot_default",
            "number": 5,
            "family": "sizing",
            "kind": "sizing",
            "rule": "Unsure of a size? Half the pot. Never the minimum",
            "why": "A tiny bet gives the opponent a great price.",
            "scope": "anyone",
            "when": {"street": POSTFLOP, "facing": "none"},
            "then": {"action": "bet", "size": 0.5},
            "source": ["GA 9:29", "GA 10:44", "MIT 3"],
        },
        {
            "id": "bluff_catcher_check_call",
            "number": 6,
            "family": "showdown_value",
            "kind": "action",
            "rule": "With a hand that beats bluffs but no good hand, check, and call if the price is good",
            "why": "A bet folds out what you beat and is called by what beats you.",
            "scope": "anyone",
            "exceptions": "More than one opponent. A good price is a bet of up to the pot: a third of the final pot.",
            "when": {"street": POSTFLOP, "hand_class": "showdown_value"},
            "unless": ["multiway"],
            "then": [
                {"if": {"facing": "none"}, "action": "check"},
                {"if": {"equity_needed": {"max": 0.34}}, "action": "call"},
                {"action": "fold"},
            ],
            "source": ["GA 11:55", "JHU 4", "JHU 5", "MIT 8"],
        },
        {
            "id": "plan_for_all_in",
            "number": 7,
            "family": "stack_depth",
            "kind": "action",
            "rule": "Before you raise, decide what you do if they move all-in. If you would fold, call instead",
            "why": "Raising and then folding throws away your hand's chance to improve.",
            "scope": "anyone",
            "exceptions": "A raise that puts you all-in, which leaves them nothing to move in with.",
            "when": {
                "street": POSTFLOP,
                "facing": ["bet", "raise"],
                "hand_class": ["showdown_value", "draw"],
                "room_to_shove": True,
            },
            # Folding and calling both keep the rule: it only rules out the raise.
            "then": {"action": "call", "accepts": ["fold", "check", "call"]},
            "source": ["GA 5:35", "GA 10:18", "JHU 6", "JHU 9"],
        },
        {
            "id": "price_to_call",
            "number": 8,
            "family": "showdown_value",
            "kind": "action",
            "rule": "The worse the price, the better the hand you need to call",
            "why": "Pot odds: call when your chance of winning beats your share of the final pot.",
            "scope": "anyone",
            "exceptions": "It counts your draw's outs as clean, with one card to come unless you are all-in.",
            "basis": "exact",
            "when": {"street": POSTFLOP, "facing": ["bet", "raise"], "hand_class": ["draw", "nothing"]},
            "then": [
                {"if": {"price_margin": {"min": 0.03}}, "action": "call"},
                {"if": {"price_margin": {"max": -0.03}}, "action": "fold"},
                {"action": "call", "accepts": ["call", "fold"], "verdict": "close"},
            ],
            "source": ["GA 19:29", "MIT 3", "JHU 2"],
        },
        {
            "id": "heads_up_pair_one_bet",
            "number": 9,
            "family": "showdown_value",
            "kind": "action",
            "rule": "Heads-up, don't fold a pair to one bet",
            "why": "With two players a pair is usually ahead.",
            "scope": "heads_up",
            "exceptions": "A raise, or a second bet in the hand.",
            "when": {"street": POSTFLOP, "heads_up": True, "pair_or_better": True, "facing": "bet", "bets_faced": 0},
            "then": {"action": "call", "accepts": ["call", "raise"]},
            "source": ["GA 13:19", "JHU 6"],
        },
        {
            "id": "short_all_in_any_ace",
            "number": 10,
            "family": "stack_depth",
            "kind": "action",
            "rule": "Facing an all-in of about 15 BB or less, call with any ace",
            "why": "Short stacks move in with a wide range.",
            "scope": "heads_up",
            "simplification": True,
            "when": {
                "street": "preflop",
                "heads_up": True,
                "facing_all_in": True,
                "facing_bb": {"max": 15.5},
                "has_ace": True,
            },
            "then": {"action": "call"},
            "source": ["GA 14:39", "JHU 6", "MIT 2"],
        },
        {
            "id": "no_bluffs_vs_caller",
            "number": 11,
            "family": "adjustments",
            "kind": "action",
            "adjustment": True,
            "read": "doesnt_fold",
            "rule": "Stop bluffing; keep betting your good hands",
            "why": "A bluff only works if they fold, and this opponent doesn't; their calls pay your good hands.",
            "scope": "doesnt_fold",
            "when": {"street": POSTFLOP, "facing": "none", "hand_class": ["strong", "draw", "nothing"]},
            "then": [
                {"if": {"hand_class": "strong"}, "action": "bet", "size": 0.5},
                {"action": "check"},
            ],
            "source": ["GA 12:48", "MIT 3", "JHU 4"],
        },
        {
            "id": "play_the_price",
            "number": 12,
            "family": "adjustments",
            "kind": "action",
            "adjustment": True,
            "read": "unknown",
            "rule": "Play the price: no hero calls and no hero folds",
            "why": "Without a read, a call or a fold against the price is a guess about a player you don't know yet.",
            "scope": "unknown",
            "when": {"street": POSTFLOP, "facing": ["bet", "raise"], "hand_class": ["strong", "nothing"]},
            "then": [
                {"if": {"hand_class": "strong"}, "action": "call", "accepts": ["call", "raise"]},
                {"action": "fold"},
            ],
            "source": ["GA 8:12", "GA 13:50", "GA 18:22"],
        },
        {
            "id": "big_bets_no_credit",
            "number": 13,
            "family": "adjustments",
            "kind": "action",
            "adjustment": True,
            "read": "big_bets_weak",
            "rule": "Stop giving big bets extra credit",
            "why": "Their big bets have shown up with weak hands, so a big bet no longer means a big hand.",
            "scope": "big_bets_weak",
            "when": {
                "street": POSTFLOP,
                "facing": ["bet", "raise"],
                "big_bet": True,
                "hand_class": ["showdown_value", "strong"],
            },
            "then": {"action": "call", "accepts": ["call", "raise"]},
            "source": ["GA 14:18"],
        },
    ],
}

HOUSE = {STARTER["key"]: STARTER}


# Playbooks a coach writes (CM-4) ---------------------------------------------------------------------------------

STREETS = ["preflop", "flop", "turn", "river"]
SEATS = ["SB", "BB", "UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN"]
ACTIONS = ["fold", "check", "call", "bet", "raise"]
# What a card's test, or a branch's, can ask of a decision (practice.spots' context and practice.rules.derived):
# each a choice of values, a yes or no, a number in a range, or a line of moves such as "check_call".
CONDITIONS = {
    "street": ("choice", STREETS, "The street"),
    "heads_up": ("bool", None, "Dealt in heads-up"),
    "multiway": ("bool", None, "More than one opponent still in"),
    "players": ("number", (2, 10), "Players still in"),
    "hero_position": ("choice", SEATS, "Your seat"),
    "position": ("choice", ["in", "out"], "In position after the flop, or out of it"),
    "preflop": ("choice", ["raised", "called_raise", "limped"], "Your part before the flop"),
    "previous": ("line", None, "Your moves on the street before, such as check_call"),
    "situation": ("choice", ["unopened", "limped", "raised", "3bet", "4bet+"], "What you face before the flop"),
    "facing": ("choice", ["none", "bet", "raise"], "What you face"),
    "facing_all_in": ("bool", None, "Facing an all-in"),
    "facing_bb": ("number", (0, 10000), "The bet you face, in big blinds"),
    "facing_pot": ("number", (0, 20), "The bet you face, as a share of the pot"),
    "bets_faced": ("number", (0, 10), "Bets faced after the flop before this one"),
    "big_bet": ("bool", None, "Facing a bet of three quarters of the pot or more"),
    "room_to_shove": ("bool", None, "Room for them to move all-in over a raise"),
    "hand_class": ("choice", ["nothing", "draw", "showdown_value", "strong"], "Your hand's class"),
    "pair_or_better": ("bool", None, "A pair or better"),
    "has_ace": ("bool", None, "An ace in your hand"),
    "equity_needed": ("number", (0, 1), "The equity a call needs"),
    "price_margin": ("number", (-1, 1), "Your draw's chance, less the equity a call needs"),
    "effective_bb": ("number", (0, 10000), "The effective stack, in big blinds"),
    "spr": ("number", (0, 1000), "The stack-to-pot ratio"),
    "pot_bb": ("number", (0, 10000), "The pot, in big blinds"),
}
SCOPES = ["anyone", "heads_up", *READS]
UNLESS = ["multiway", "short"]  # practice.rules.EXCEPTIONS
MAX_CARDS = 40
MAX_BRANCHES = 6
LIMITS = {"rule": 160, "why": 400, "exceptions": 300, "source": 40, "name": 100, "description": 1000}


class PlaybookError(ValueError):
    """A playbook's cards don't hold together; `errors` says where, card by card."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def clean_rules(rules):
    """A coach's cards, checked and tidied for the rule engine: numbered in order, with only the fields it reads.
    PlaybookError lists every problem found."""
    errors = []
    if not isinstance(rules, list) or not rules:
        raise PlaybookError(["A playbook needs at least one card."])
    if len(rules) > MAX_CARDS:
        errors.append(f"A playbook holds at most {MAX_CARDS} cards.")
    cleaned, ids = [], set()
    for number, card in enumerate(rules[:MAX_CARDS], start=1):
        found = []
        tidy = _card(card, number, found) if isinstance(card, dict) else None
        if tidy is None and not found:
            found.append("isn't a card")
        if tidy and tidy["id"] in ids:
            found.append(f"its id {tidy['id']!r} is another card's")
        errors += [f"Card {number}: {problem}." for problem in found]
        if tidy:
            ids.add(tidy["id"])
            cleaned.append(tidy)
    if errors:
        raise PlaybookError(errors)
    return cleaned


def _card(card, number, found):
    tidy = {"number": number}
    card_id = card.get("id")
    if not isinstance(card_id, str) or not (2 <= len(card_id) <= 40) or not card_id.replace("_", "").isalnum():
        found.append("its id must be 2 to 40 letters, digits or underscores")
    tidy["id"] = str(card_id).lower() if card_id else ""
    for field in ("family", "kind", "scope"):
        allowed = {"family": list(FAMILIES), "kind": ["action", "sizing"], "scope": SCOPES}[field]
        if card.get(field) not in allowed:
            found.append(f"its {field} must be one of {', '.join(allowed)}")
        tidy[field] = card.get(field)
    for field in ("rule", "why", "exceptions"):
        text = card.get(field, "")
        required = field != "exceptions"
        if not isinstance(text, str) or len(text) > LIMITS[field] or (required and not text.strip()):
            found.append(f"its {field} must be {'' if required else 'empty or '}text of up to {LIMITS[field]} characters")
        elif text.strip():
            tidy[field] = text.strip()
    source = card.get("source", [])
    if not isinstance(source, list) or len(source) > 8 or not all(
        isinstance(item, str) and 0 < len(item) <= LIMITS["source"] for item in source
    ):
        found.append("its sources must be up to 8 short citations")
    tidy["source"] = [item.strip() for item in source if isinstance(item, str)] if isinstance(source, list) else []
    for flag in ("simplification", "adjustment"):
        if card.get(flag):
            tidy[flag] = True
    if tidy.get("adjustment"):
        if card.get("read") not in READS:
            found.append(f"an adjustment needs the read that unlocks it: one of {', '.join(READS)}")
        tidy["read"] = card.get("read")
    if card.get("basis") not in (None, "exact"):
        found.append('its basis, if any, must be "exact"')
    elif card.get("basis"):
        tidy["basis"] = "exact"
    unless = card.get("unless", [])
    if not isinstance(unless, list) or any(item not in UNLESS for item in unless):
        found.append(f"its exceptions to test must be among {', '.join(UNLESS)}")
    elif unless:
        tidy["unless"] = list(dict.fromkeys(unless))
    tidy["when"] = _conditions(card.get("when"), "its test", found, required=True)
    tidy["then"] = _branches(card.get("then"), tidy.get("kind"), found)
    return tidy


def _conditions(test, where, found, required=False):
    """A test: {condition: value}, each condition one of CONDITIONS with a value of its kind."""
    if not isinstance(test, dict) or (required and not test):
        found.append(f"{where} needs at least one condition" if required else f"{where} must be conditions")
        return {}
    tidy = {}
    for key, wanted in test.items():
        if key not in CONDITIONS:
            found.append(f"{where} can't test {key!r}")
            continue
        kind, allowed, _ = CONDITIONS[key]
        if kind == "bool" and isinstance(wanted, bool):
            tidy[key] = wanted
        elif kind == "choice" and (wanted in allowed or (
            isinstance(wanted, list) and wanted and all(item in allowed for item in wanted)
        )):
            tidy[key] = wanted
        elif kind == "line" and isinstance(wanted, str) and wanted.replace("_", "").isalpha():
            tidy[key] = wanted
        elif kind == "number" and _number(wanted, allowed):
            tidy[key] = wanted
        else:
            found.append(f"{where} has a value for {key!r} that doesn't fit it")
    return tidy


def _number(wanted, bounds):
    """A number within bounds, or {"min", "max"} with at least one of them, each within bounds, min below max."""
    low, high = bounds
    if isinstance(wanted, bool):
        return False
    if isinstance(wanted, int | float):
        return low <= wanted <= high
    if not isinstance(wanted, dict) or not wanted or set(wanted) - {"min", "max"}:
        return False
    values = list(wanted.values())
    if not all(isinstance(value, int | float) and not isinstance(value, bool) for value in values):
        return False
    return all(low <= value <= high for value in values) and wanted.get("min", low) <= wanted.get("max", high)


def _branches(then, kind, found):
    """What a card says to do: one branch, or a list tried in order, each with its own test (`if`) but the last."""
    branches = then if isinstance(then, list) else [then]
    if not branches or len(branches) > MAX_BRANCHES or not all(isinstance(branch, dict) for branch in branches):
        found.append(f"its move must be one branch or a list of up to {MAX_BRANCHES}")
        return []
    tidy = []
    for number, branch in enumerate(branches, start=1):
        where = f"branch {number}" if len(branches) > 1 else "its move"
        action = branch.get("action")
        if action not in ACTIONS:
            found.append(f"{where} needs an action: one of {', '.join(ACTIONS)}")
            continue
        clean = {"action": action}
        if "if" in branch:
            clean["if"] = _conditions(branch["if"], f"{where}'s test", found)
        if "size" in branch:
            if action != "bet" or not _number(branch["size"], (0.05, 3)):
                found.append(f"{where}'s size must be a bet's share of the pot, from 0.05 to 3")
            clean["size"] = branch["size"]
        if "to_bb" in branch:
            if action != "raise" or not _number(branch["to_bb"], (1, 50)):
                found.append(f"{where}'s raise must make the bet 1 to 50 big blinds")
            clean["to_bb"] = branch["to_bb"]
        accepts = branch.get("accepts")
        if accepts is not None:
            if not isinstance(accepts, list) or action not in accepts or any(item not in ACTIONS for item in accepts):
                found.append(f"{where}'s moves that keep it must be actions, its own among them")
            clean["accepts"] = accepts
        if branch.get("verdict") not in (None, "clear", "close"):
            found.append(f'{where}\'s verdict, if any, must be "clear" or "close"')
        elif branch.get("verdict"):
            clean["verdict"] = branch["verdict"]
        tidy.append(clean)
    if kind == "sizing" and any(branch["action"] != "bet" or "size" not in branch for branch in tidy):
        found.append("a sizing card says how much to bet: every branch a bet with its size")
    return tidy if isinstance(then, list) else (tidy[0] if tidy else {})
