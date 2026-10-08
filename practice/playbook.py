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
