"""The arithmetic behind a decision, asked as questions with exact answers.

`arithmetic(context, hand)` asks for the numbers the decision panel shows at a spot (practice.spots' context):
the equity a call needs, the pot odds, the minimum defense frequency, how often a bluff must work, and M in a
tournament. Each is a choice of four, as quick on a phone as at a desk. The wrong options are the usual
mistakes: leaving your own call out of the pot, reading a bet's size as its price, taking the defense frequency
for the equity a call needs [MIT 3; MIT 7; JHU 2].

A question's amounts are written into its text as {a0}, {a1}, ..., with their chips in `amounts`, so the client
writes them in the table's unit: the hand's own chips or money, or big blinds.

Django-free, like practice.spots.
"""

import random

TOPICS = {
    "equity_needed": "Equity needed to call",
    "pot_odds": "Pot odds",
    "mdf": "Minimum defense frequency",
    "bluff_break_even": "How often a bluff must work",
    "m": "Harrington's M",
}
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}
# Wrong options are at least this far from every other option, so a rounding never decides the answer.
MIN_GAP = {"percent": 3, "ratio": 0.3, "number": 0.6}


def money(amount, currency=""):
    """Chips as "1,100", or cents as "$1.10" ("$2" when whole), as the hand's amounts read."""
    if not currency:
        return f"{amount:,}"
    value = f"{amount / 100:,.0f}" if amount % 100 == 0 else f"{amount / 100:,.2f}"
    symbol = SYMBOLS.get(currency)
    return f"{symbol}{value}" if symbol else f"{value} {currency}"


def percent(share):
    return f"{round(share * 100)}%"


def ratio(value):
    return f"{value:.1f} : 1"


class _Amounts(dict):
    """The amounts a question's text holds, as {a0}, {a1}, ... by their chips; the same amount keeps its key."""

    def __call__(self, chips):
        key = next((key for key, value in self.items() if value == chips), f"a{len(self)}")
        self[key] = chips
        return "{" + key + "}"


def arithmetic(context, hand, rng=None):
    """The questions a spot can ask, by topic: {topic: {"question": ..., "answer": ...}}.

    `hand` gives the blinds and antes behind M. A bluff's question needs the hero's bet, so only a decision that
    has its move (practice.spots.decisions) asks it.
    """
    rng = rng or random.Random()
    cash = _Amounts()
    asked = {}
    if context["equity_needed"] is not None:
        bettor, to_call, pot = context["bettor"], context["to_call"], context["pot_if_call"]
        facing = _facing_text(context, cash)
        needed = to_call / pot
        without_call = to_call / (pot - to_call)
        asked["equity_needed"] = _choice(
            f"{facing} What share of the pot after your call is your call: the equity you need?",
            needed,
            [without_call, context["bet"] / context["pot_before"], needed * 2],
            "percent",
            f"Your call of {cash(to_call)} ÷ the {cash(pot)} pot after it = {percent(needed)}. Call when your "
            "chance of winning is more than that.",
            "call ÷ (pot + call)",
            rng,
        )
        odds = (pot - to_call) / to_call
        asked["pot_odds"] = _choice(
            f"{facing} What pot odds are you getting?",
            odds,
            [pot / to_call, context["pot_before"] / to_call, odds / 2],
            "ratio",
            f"{cash(pot - to_call)} in the pot against your {cash(to_call)} call: {ratio(odds)}. In odds against, "
            f"you need to win more than once in {odds + 1:.1f} tries.",
            "pot : call",
            rng,
        )
        if bettor and context["mdf"] is not None:
            bet, before = context["bet"], context["pot_before"]
            asked["mdf"] = _choice(
                f"{facing} How often must you continue so that a bluff of this size can't profit?",
                context["mdf"],
                [bet / (before + 2 * bet), bet / (before + bet), 1 - bet / before if bet < before else 0.15],
                "percent",
                f"The pot before the bet ÷ (the pot + the bet) = {cash(before)} ÷ {cash(before + bet)} = "
                f"{percent(context['mdf'])}. Fold more often than that and the bet profits with any two cards.",
                "pot ÷ (pot + bet)",
                rng,
            )
    move = context.get("move")
    if move and move["action"] in ("bet", "raise") and move.get("pot_before"):
        amount, before = move["amount"], move["pot_before"]
        need = amount / (before + amount)
        verb = "bet" if move["action"] == "bet" else "raise, putting in"
        asked["bluff_break_even"] = _choice(
            f"You {verb} {cash(amount)} with {cash(before)} in the middle. How often must it make them fold, "
            "as a pure bluff, to break even?",
            need,
            [amount / before, before / (before + amount), amount / (before + 2 * amount)],
            "percent",
            f"Your bet ÷ (the pot + your bet) = {cash(amount)} ÷ {cash(before + amount)} = {percent(need)}.",
            "bet ÷ (pot + bet)",
            rng,
        )
    if hand.get("tournament_id"):
        hero = next(player for player in hand["players"] if player["name"] == hand["hero"])
        antes = sum(event["amount"] for event in hand["events"] if event.get("blind") == "ante")
        sb, bb = hand["small_blind"], hand["big_blind"]
        m = hero["stack"] / (sb + bb + antes)
        ante_text = f" + {cash(antes)} in antes" if antes else ""
        asked["m"] = _choice(
            f"You started the hand with {cash(hero['stack'])} at {cash(sb)}/{cash(bb)}{ante_text}. What is your M?",
            m,
            [hero["stack"] / bb, hero["stack"] / (sb + bb) if antes else hero["stack"] / (2 * bb), m / 2],
            "number",
            f"Your stack ÷ (small blind + big blind + antes) = {cash(hero['stack'])} ÷ {cash(sb + bb + antes)} = "
            f"{m:.1f}: the rounds you would last by folding.",
            "stack ÷ (small blind + big blind + antes)",
            rng,
        )
    for item in asked.values():
        item["question"]["amounts"] = item["answer"]["amounts"] = dict(cash)
    return asked


def _facing_text(context, cash):
    if context["facing"] == "bet":
        return f"{context['bettor']} bets {cash(context['bet'])} into {cash(context['pot_before'])}."
    all_in = " all-in" if context["facing_all_in"] else ""
    return (
        f"{context['bettor']} raises{all_in} to {cash(context['facing_to'])}: {cash(context['to_call'])} for you "
        f"to call, with {cash(context['pot'])} in the middle."
    )


def _choice(prompt, value, mistakes, unit, explanation, formula, rng):
    """A question of four options: the answer and the likeliest mistakes, topped up around the answer."""
    show = {"percent": lambda v: round(v * 100), "ratio": lambda v: round(v, 1), "number": lambda v: round(v, 1)}[unit]
    gap = MIN_GAP[unit]
    low = 1 if unit == "percent" else 0.1
    high = 99 if unit == "percent" else float("inf")
    answer = show(value)
    shown = [answer]
    step = {"percent": 0.06, "ratio": 0.35, "number": 0.3}[unit]
    near = [value * (1 + step * k) if unit != "percent" else value + step * k for k in (1, -1, 2, -2, 3, -3, 4, 5)]
    for candidate in [*mistakes, *near]:
        option = show(candidate)
        if low <= option <= high and all(abs(option - other) >= gap for other in shown):
            shown.append(option)
        if len(shown) == 4:
            break
    rng.shuffle(shown)
    text = {"percent": lambda v: f"{v}%", "ratio": lambda v: f"{v:.1f} : 1", "number": lambda v: f"{v:.1f}"}[unit]
    return {
        "question": {"kind": "choice", "prompt": prompt, "options": [text(option) for option in shown], "unit": unit},
        "answer": {
            "correct": shown.index(answer),
            "value": round(value, 4),
            "explanation": explanation,
            "formula": formula,
        },
    }
