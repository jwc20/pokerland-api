"""Runs a playbook's rule cards (practice.playbook) over decisions: what they advise, and whether a move kept them.

`evaluate(context, rules, reads)` settles what the coach says about a decision: the action and the size, the rule
in play, a verdict and its basis.

- **Verdicts.** *Clear*: a rule decides it, and it counts toward the scores. *Close*: either action is fine, or
  two rules disagree; it doesn't count. *Your call*: it turns on a read with thin evidence, and goes to the
  calibration journal.
- **Bases**, named on the coach's rail: *exact* (the price against your outs, all public), *rule* (a playbook
  card), *adjustment* (a card a read unlocked), *none* (nothing firm: the coach leans, and says it is close).
- **Reads unlock adjustments by degree** [MIT 8]. Thin evidence lets an adjustment settle close decisions only,
  as "your call"; strong evidence lets it overrule the defaults.

`check(context, move, rules)` says which cards applied to a decision already made, and whether the move kept
each: the playbook's "by the book" in stored hands. The same functions run at a practice table and over stored
hands. Django-free, like practice.spots.
"""

from math import comb

# A bet within this much of the size a card asks for, as a share of the pot, keeps it.
SIZE_TOLERANCE = 0.1
# Above this a bet is a big one: the read card's "big bet = big hand?" [GA 14:22].
BIG_BET = 0.75
# A raise of three times the bet that still leaves chips behind gives them room to move all-in over it.
RAISE_MULTIPLE = 3
# Ten big blinds or less, a raise is a move all-in [JHU 6].
SHORT_BB = 10
# Outs for each draw (tracker.parsing.facts.draws); a flush draw with a straight draw shares two of them.
OUTS = {"nut_flush_draw": 9, "flush_draw": 9, "open_ended": 8, "double_gutshot": 8, "gutshot": 4}
# Exceptions a card can name in `unless`.
EXCEPTIONS = {
    "multiway": lambda context: context["multiway"],
    "short": lambda context: context["effective_bb"] <= SHORT_BB,
}


def outs(drawing):
    """How many cards improve the draws: the most of any one, plus a straight draw's beside a flush draw."""
    counts = sorted((OUTS[draw] for draw in drawing if draw in OUTS), reverse=True)
    if not counts:
        return 0
    flush = any("flush_draw" in draw and not draw.startswith("backdoor") for draw in drawing)
    if flush and len(counts) > 1:
        return counts[0] + counts[1] - 2 + (counts[1] == 4)  # a gutshot shares one out with the flush draw
    return counts[0]


def draw_equity(outs_count, board_cards, all_in):
    """The chance that `outs_count` clean outs come: on the next card, or by the river when no more betting is due.

    The rule of 2 and 4 estimates the same thing [MIT 3; JHU 7]; this is its exact form.
    """
    if not outs_count or board_cards >= 5:
        return 0.0
    unseen = 52 - 2 - board_cards
    if all_in and board_cards == 3:
        return 1 - comb(unseen - outs_count, 2) / comb(unseen, 2)
    return outs_count / unseen


def derived(context):
    """The context with what the cards test on top of practice.spots': outs, their chance against the price, ..."""
    context = dict(context)
    count = outs(context.get("draws") or [])
    equity = draw_equity(count, len(context.get("board") or []), context.get("facing_all_in", False))
    needed = context.get("equity_needed")
    facing_bb = context.get("facing_bb") or 0
    context.update(
        outs=count,
        draw_equity=round(equity, 4),
        price_margin=None if needed is None else round(equity - needed, 4),
        big_bet=(context.get("facing_pot") or 0) >= BIG_BET,
        room_to_shove=context["effective_bb"] > RAISE_MULTIPLE * facing_bb,
    )
    return context


def matches(test, context):
    """Whether `context` passes every condition in `test`: a value, any of a list, or a {"min", "max"} range."""
    for key, wanted in test.items():
        value = context.get(key)
        if isinstance(wanted, dict):
            if value is None or value < wanted.get("min", value) or value > wanted.get("max", value):
                return False
        elif isinstance(wanted, list):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True


def play(rule, context):
    """What `rule` says to do in `context`, or None if it doesn't apply.

    {"rule", "family", "kind", "action", "accepts", "size", "to_bb", "verdict", "basis"}, with `accepts` the
    moves that keep the rule.
    """
    if not matches(rule["when"], context) or any(EXCEPTIONS[name](context) for name in rule.get("unless", ())):
        return None
    branches = rule["then"] if isinstance(rule["then"], list) else [rule["then"]]
    branch = next((branch for branch in branches if matches(branch.get("if", {}), context)), None)
    if branch is None:
        return None
    return {
        "rule": rule["id"],
        "family": rule["family"],
        "kind": rule["kind"],
        "action": branch["action"],
        "accepts": list(branch.get("accepts", [branch["action"]])),
        "size": branch.get("size"),
        "to_bb": branch.get("to_bb"),
        "verdict": branch.get("verdict", "clear"),
        "basis": "adjustment" if rule.get("adjustment") else rule.get("basis", "rule"),
    }


def evaluate(context, rules, reads=None):
    """What the playbook says about a decision: an advice dict, as the module describes.

    `reads` maps the read card's reads (practice.playbook.READS) to "thin" or "strong" evidence.
    """
    context = derived(context)
    reads = reads or {}
    plays = [found for rule in rules if not rule.get("adjustment") and (found := play(rule, context))]
    advice = settle([found for found in plays if found["kind"] == "action"])
    for rule in rules:
        evidence = reads.get(rule.get("read"))
        if not rule.get("adjustment") or evidence is None or (found := play(rule, context)) is None:
            continue
        if evidence == "strong" or advice is None or advice["verdict"] != "clear":
            advice = {
                **found,
                "verdict": "clear" if evidence == "strong" else "your_call",
                "rules": [*(advice["rules"] if advice else []), found["rule"]],
            }
    if advice is None:
        advice = lean(context)
    if advice["action"] == "bet" and advice["size"] is None:
        sizing = next((found for found in plays if found["kind"] == "sizing"), None)
        advice["size"] = sizing["size"] if sizing else 0.5
        if sizing:
            advice["sizing_rule"] = sizing["rule"]
    advice["family"] = advice.get("family") or family_of(context)
    advice["outs"] = context["outs"]
    advice["draw_equity"] = context["draw_equity"]
    return advice


def settle(plays):
    """One advice from the action cards that apply: the moves they all accept, or "close" when there are none."""
    if not plays:
        return None
    accepted = set.intersection(*(set(found["accepts"]) for found in plays))
    rules = [found["rule"] for found in plays]
    if not accepted:
        first = plays[0]
        accepts = sorted({action for found in plays for action in found["accepts"]})
        return {**first, "accepts": accepts, "verdict": "close", "basis": "rule", "rules": rules, "conflict": True}
    # The card in play is the most decisive: a card that only rules a move out (rule 7) gives way to one that
    # says which move to make.
    agreeing = [found for found in plays if found["action"] in accepted] or plays
    primary = min(agreeing, key=lambda found: len(found["accepts"]))
    verdict = "close" if any(found["verdict"] == "close" for found in plays) else "clear"
    return {**primary, "accepts": sorted(accepted), "verdict": verdict, "rules": rules}


def family_of(context):
    """The rule family a decision no card covers belongs to, for the coach's stage."""
    if context["facing_all_in"]:
        return "stack_depth"
    if context["street"] == "preflop":
        return "button" if context["hero_position"] == "BTN" else "out_of_position"
    if context["facing"] != "none":
        return "showdown_value"
    return "sizing" if context["position"] == "in" else "out_of_position"


def lean(context):
    """What the coach leans to where no card decides: a sound, simple default, said to be close."""
    action, size, to_bb = "check", None, None
    street, facing = context["street"], context["facing"]
    if street == "preflop":
        score = chen(context["cards"])
        if facing == "none":
            if context["to_call"] == 0:
                action, to_bb = ("raise", 3) if score >= 9 else ("check", None)
            else:
                action, to_bb = ("raise", 2.5) if score >= 6 else ("fold", None)
        elif context["facing_all_in"]:
            action = "call" if score >= 8 else "fold"
        elif score >= 12:
            action, to_bb = "raise", round(3 * (context["facing_bb"] or 3), 1)
        else:
            action = "call" if score >= (4 if context["heads_up"] else 7) else "fold"
    elif facing == "none":
        held = context["hand_class"]
        cbet = street == "flop" and context["aggressor"] == "hero" and not context["multiway"]
        semi_bluff = held == "draw" and (context["position"] == "in" or cbet)
        if held == "strong" or semi_bluff or (held == "nothing" and cbet):
            action, size = "bet", 0.5
    else:
        action = "call" if context["hand_class"] in ("strong", "showdown_value") else "fold"
    return {
        "rule": None,
        "family": None,
        "kind": "action",
        "action": action,
        "accepts": [action],
        "size": size,
        "to_bb": to_bb,
        "verdict": "close",
        "basis": "none",
        "rules": [],
    }


def follows(advice, move):
    """Whether a move keeps the advice: an action it accepts, and for a bet, the size it asks for."""
    if move["action"] not in advice["accepts"]:
        return False
    if move["action"] == "bet" and advice.get("size") is not None and move.get("size") is not None:
        return abs(move["size"] - advice["size"]) <= SIZE_TOLERANCE
    return True


def check(context, move, rules):
    """Each default card that applied to a decision, and whether the move kept it: [{"rule", "followed"}].

    An action card applies wherever its test passes, and is kept by any move it accepts. A sizing card applies
    only to a bet in its spot, and is kept by a bet of its size; the first sizing card that applies speaks for
    the rest. Adjustments need a read, which stored hands don't have.
    """
    context = derived(context)
    results = []
    sized = False
    for rule in rules:
        if rule.get("adjustment") or (found := play(rule, context)) is None:
            continue
        if rule["kind"] == "sizing":
            if move["action"] != "bet" or sized:
                continue
            sized = True
            size = move.get("size")
            kept = size is not None and abs(size - found["size"]) <= SIZE_TOLERANCE
        else:
            kept = move["action"] in found["accepts"]
        results.append({"rule": rule["id"], "followed": kept})
    return results


RANKS = "23456789TJQKA"


def chen(cards):
    """Bill Chen's score for two hole cards, from -1 (seven-deuce) to 20 (aces); 0 for anything else, as Omaha."""
    if len(cards) != 2:
        return 0
    high, low = sorted(cards, key=lambda card: RANKS.index(card[0]), reverse=True)
    top, bottom = RANKS.index(high[0]) + 2, RANKS.index(low[0]) + 2
    points = {14: 10, 13: 8, 12: 7, 11: 6}.get(top, top / 2)
    if top == bottom:
        return max(5, points * 2)
    if high[1] == low[1]:
        points += 2
    gap = top - bottom - 1
    points -= (0, 1, 2, 4)[gap] if gap < 4 else 5
    if gap <= 1 and top < 12:
        points += 1
    return int(-(-points // 1))  # half points round up
