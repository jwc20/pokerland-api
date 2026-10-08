"""The coach of a coached match: what it says at each stage, and how it hands a rule family over.

The handover ladder (pokerland-practice-mode-additional.md, 4.3) has four stages. At 1, *watch*, the coach names
the move and says why; at 2, *call it*, it asks what you are thinking and confirms or corrects you; at 3, *play,
then hear it*, it says nothing until the hand is over, then comments on one decision at most; at 4, *solo*, it
waits for the debrief. Each rule family moves on its own: up a stage when 8 of its last 10 decisions a rule
settled kept the playbook without asking the coach, down one after 3 misses in its last 5.

Every line is a template, fixed and testable. The coach sees only what the player sees: the cards they hold,
the board, the action and the read. It never chooses a move: practice.rules does.
"""

from practice.playbook import FAMILIES

UP = (8, 10)  # kept, of the last decisions
DOWN = (3, 5)  # missed, of the last decisions
KEPT = max(UP[1], DOWN[1])  # how many results a family keeps

SIZES = {
    0.25: "a quarter of the pot",
    0.33: "a third of the pot",
    0.5: "half the pot",
    0.75: "three quarters of the pot",
}
REASONS = {
    "value": "worse hands call",
    "bluff": "better hands fold",
    "draw": "you have a draw",
    "protect": "to charge the draws",
    "bluff_catch": "it beats bluffs only",
    "price": "the price is good",
    "trap": "to trap",
    "give_up": "you're giving up",
    "cant_say": "you can't say",
}


def record(row, kept):
    """Adds a decision a rule settled to a family's progress, moving its stage up or down. Returns the change."""
    row.recent = [*row.recent, bool(kept)][-KEPT:]
    if row.stage < 4 and sum(row.recent[-UP[1] :]) >= UP[0]:
        row.stage += 1
        row.recent = []
        return 1
    if row.stage > 1 and row.recent[-DOWN[1] :].count(False) >= DOWN[0]:
        row.stage -= 1
        row.recent = []
        return -1
    return 0


def size_text(size):
    """A bet's size in words: "half the pot", "60% of the pot"."""
    near = min(SIZES, key=lambda share: abs(share - size))
    return SIZES[near] if abs(near - size) < 0.03 else f"{round(size * 100)}% of the pot"


def move_text(advice):
    """The move the advice names: "Check", "Bet half the pot", "Raise to 2.5 bb"."""
    action = advice["action"]
    if action == "bet":
        return f"Bet {size_text(advice['size'] or 0.5)}"
    if action == "raise" and advice.get("to_bb"):
        return f"Raise to {advice['to_bb']:g} bb"
    return action.capitalize()


def advice_line(advice, cards, context):
    """What the coach says about a decision before it is made: the move, then why.

    `cards` maps the playbook's rule ids to their cards; `context` is the decision's (practice.spots).
    """
    move = move_text(advice)
    card = cards.get(advice["rule"])
    if advice["verdict"] == "close" and advice.get("conflict"):
        first, *others = [cards[rule] for rule in advice["rules"] if rule in cards]
        other = next((rule for rule in others if rule["number"] != first["number"]), first)
        return (
            f"It's close. Rule {first['number']} says {first['rule'][0].lower()}{first['rule'][1:]}; "
            f"rule {other['number']} says {other['rule'][0].lower()}{other['rule'][1:]}. You could do either."
        )
    if advice["basis"] == "exact" and card:
        needed = context.get("equity_needed") or 0
        outs = advice.get("outs") or 0
        chance = round(advice["draw_equity"] * 100)
        coming = f"your {outs} outs come {chance}% of the time" if outs else "you have no outs"
        verdict = "Close: you could do either." if advice["verdict"] == "close" else f"{move}."
        return f"You need {round(needed * 100)}% to call and {coming}. {verdict}"
    if advice["verdict"] == "your_call" and card:
        return f"{move}, if your read is right: {card['rule'][0].lower()}{card['rule'][1:]}. {card['why']}"
    if card:
        return f"{move}. {card['why']}"
    return f"It's close; no rule settles this one. I'd {move[0].lower()}{move[1:]}: {lean_reason(advice, context)}"


def lean_reason(advice, context):
    """Why the coach leans the way it does where no card decides."""
    action, held = advice["action"], context.get("hand_class")
    if context["street"] == "preflop":
        worth = action in ("call", "raise")
        return "this hand is worth it at the price." if worth else "this hand isn't worth the price."
    if held == "strong":
        return "you have a good hand, so make worse hands pay." if action == "bet" else "you're ahead of their bets."
    if held == "draw":
        return "a draw likes to bet when it can win at once or improve." if action == "bet" else "take the free card."
    if held == "nothing" and action == "bet":
        return "as the raiser, a small bet takes the pot often enough."
    return "there's little to gain by putting more in."


def verdict_line(advice, intent, kept):
    """What the coach says once the player has said what they would do (stage 2)."""
    if advice["verdict"] == "close":
        return "It's close. You could do either way."
    if advice["verdict"] == "your_call":
        lean = "I'd do the same." if kept else f"I'd {move_text(advice).lower()}."
        return f"That one turns on your read of them. {lean}"
    if kept:
        return "That is the right decision."
    return f"I'd {move_text(advice)[0].lower()}{move_text(advice)[1:]} here."


def reason_note(reason, action, context):
    """Whether the reason fits the move and the hand: the same move is right for one reason and wrong for another.

    Returns (fits, note); `note` is empty when the reason fits.
    """
    held = context.get("hand_class")
    if reason == "cant_say":
        return False, "If you can't say why you're betting, then maybe you shouldn't be betting."
    if reason is None or held is None:
        return True, ""  # before the flop there is no hand class to weigh a reason against
    if reason == "value" and held != "strong":
        if held == "showdown_value":
            return False, (
                "Worse hands won't call and better hands won't fold: that hand can beat a bluff but can't beat any "
                "good hands."
            )
        return False, "With nothing yet, worse hands won't call."
    if reason == "bluff" and held in ("strong", "showdown_value"):
        if held == "strong":
            return False, "That's a good hand: worse hands call it, so it's a value bet, not a bluff."
        return False, "Better hands won't fold, and a bet turns a hand that wins at showdown into a bluff."
    if reason == "draw" and held != "draw":
        return False, "There's no draw of eight outs or more here."
    if reason == "bluff_catch" and held != "showdown_value":
        if held == "strong":
            return False, "You beat more than bluffs: some value hands too."
        return False, "With nothing, you beat few bluffs."
    if reason == "price" and action == "call":
        needed = context.get("equity_needed") or 0
        if held == "nothing" or (held == "showdown_value" and needed > 0.34):
            return False, f"At this price you need {round(needed * 100)}%: more than this hand wins."
    if reason == "trap" and held != "strong":
        return False, "There's nothing to trap with."
    if reason == "give_up" and held in ("strong", "showdown_value"):
        return False, "This hand is worth more than giving up."
    return True, ""


def after_hand(decisions, cards):
    """The one comment the coach makes after a hand at stage 3: on the decision that left a clear rule, if any.

    `decisions` are the hand's MatchDecisions, in order.
    """
    missed = [d for d in decisions if d.followed is False and d.advice["verdict"] == "clear" and d.stage == 3]
    if not missed:
        return None
    decision = missed[0]
    card = cards.get(decision.advice["rule"])
    when = street_phrase(decision.context["street"])
    move = decision.move["action"] if decision.move else ""
    reason = f" {card['why']}" if card else ""
    return {
        "step": decision.step,
        "line": f"{when[0].upper()}{when[1:]} you chose to {move}. The playbook would "
        f"{move_text(decision.advice).lower()}.{reason}",
    }


def street_phrase(street):
    """"before the flop", "on the turn"."""
    return "before the flop" if street == "preflop" else f"on the {street}"


def family_label(family):
    return FAMILIES.get(family, family)


def situation(context):
    """The spot in a line, as the coach opens it at stage 2: "He raised, you called, you act first."."""
    street, facing = context["street"], context["facing"]
    if street == "preflop":
        if facing == "none":
            if context["to_call"]:
                return "It's folded to you on the button."
            return "He limped in; you have the option."
        if context["facing_all_in"]:
            return f"He moves all-in for {context['facing_bb']:g} bb."
        return f"He raises to {context['facing_bb']:g} bb."
    first = {
        "called_raise": "He raised, you called",
        "raised": "You raised, he called",
        "limped": "You limped",
    }.get(context["preflop"], "")
    if facing != "none":
        size = context["facing_pot"]
        sized = f", {round(size * 100)}% of the pot" if size else ""
        verb = "raises" if facing == "raise" else "bets"
        return f"On the {street} he {verb} {context['facing_bb']:g} bb{sized}."
    if context["checks"]:
        if street == "flop":
            return f"{first}; he checks to you on the flop."
        return f"He checks to you on the {street}."
    acting = "you act first" if context["position"] == "out" else "it's your turn"
    return f"{first}, {acting}." if street == "flop" else f"On the {street}, {acting}."
