"""Tournament facts from a hand's text (FND-8 of the feature ideas): the buy-in, the level, and who finished the
tournament or won a bounty in the hand.

PokerStars writes the buy-in in a tournament hand's first line:

    PokerStars Hand #219400000001: Tournament #2981073415, $0.98+$0.12 USD Hold'em No Limit - Level III (25/50) - ...

first the part that goes to the prize pool, then the fee; a bounty tournament's has three parts, the bounty in the
middle ($1+$1+$0.20). A freeroll says "Freeroll", and a play-money buy-in has no currency. The hand in which a player
busts, or wins, says so, as may a bounty won:

    Carol finished the tournament in 4th place
    Bob finished the tournament in 3rd place and received $3.20.
    Alice wins the tournament and receives $10.80 - congratulations!
    Alice wins the $0.50 bounty for eliminating Bob
    Alice wins $0.50 for eliminating Bob and their own bounty increases by $0.50 to $1.50

These are PokerStars' wordings as they are known, and the fixtures are written in them; they have not been checked
against real tournament files yet (the feature ideas' risk 2). A line worded otherwise is simply not read: the
tournament then shows no finish or prize until its owner enters them. Like the rest of tracker.parsing, this module
never imports Django.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

GAMES = ("Hold'em No Limit", "Omaha Pot Limit")
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
HEADER = re.compile(rf"Tournament #(?P<id>\d+), (?P<entry>.*?) (?:{'|'.join(GAMES)})")
LEVEL = re.compile(r" - (?:.*?, )?Level (?P<level>[IVXLCDM]+|\d+)\b")
CODE = re.compile(r"\s+(?P<code>[A-Z]{3})$")
FINISHED = re.compile(
    r"^(?P<player>.+?) finished the tournament in (?P<place>\d+)(?:st|nd|rd|th) place"
    r"(?: and received (?P<prize>.+?))?\.?\s*$",
    re.MULTILINE,
)
WON = re.compile(
    r"^(?P<player>.+?) wins the tournament and receives (?P<prize>.+?) - congratulations!\s*$", re.MULTILINE
)
BOUNTY = re.compile(
    r"^(?P<player>.+?) wins the (?P<amount>\S+) bounty for eliminating (?P<eliminated>.+?)\s*$", re.MULTILINE
)
# A progressive knockout: half the bounty is won, half goes on the winner's own head. "splitting the elimination"
# when two players knock one out together.
PROGRESSIVE = re.compile(
    r"^(?P<player>.+?) wins (?P<amount>\S+) for (?:splitting the elimination of|eliminating) (?P<eliminated>.+?) "
    r"and their own bounty increases by \S+ to \S+?\.?\s*$",
    re.MULTILINE,
)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
NO_ENTRY = {"buy_in": 0, "fee": 0, "bounty": 0, "currency": "", "play_money": False, "freeroll": False}


def roman(numeral):
    """A Roman numeral's value: "XIV" is 14."""
    values = [ROMAN[letter] for letter in numeral]
    return sum(-value if i + 1 < len(values) and value < values[i + 1] else value for i, value in enumerate(values))


def amount(text, money):
    """An amount such as "$0.98", "€4.60" or "1,500": cents when `money`, chips otherwise; None if it isn't one."""
    digits = text.strip().rstrip(".").lstrip("".join(SYMBOLS)).replace(",", "")
    try:
        value = Decimal(digits) * (100 if money else 1)
    except InvalidOperation:
        return None
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def entry(header):
    """The buy-in of a tournament hand's first line: {buy_in, fee, bounty, currency, play_money, freeroll}."""
    match = HEADER.search(header)
    if not match:
        return None
    text = match["entry"].strip()
    if text.lower().startswith("freeroll"):
        return {**NO_ENTRY, "freeroll": True}
    code = CODE.search(text)
    if code:
        text = text[: code.start()]
    parts = [part.strip() for part in text.split("+") if part.strip()]
    symbol = next((part[0] for part in parts if part[0] in SYMBOLS), "")
    money = bool(code or symbol)
    values = [amount(part, money) or 0 for part in parts]
    # The prize pool's part comes first and the fee last; a bounty, when there is one, between them.
    bounty = values[1] if len(values) == 3 else 0
    return {
        "buy_in": values[0] if values else 0,
        "fee": values[-1] if len(values) > 1 else 0,
        "bounty": bounty,
        "currency": code["code"] if code else SYMBOLS.get(symbol, ""),
        "play_money": not money,
        "freeroll": False,
    }


def level(header):
    """The blind level in a tournament hand's first line, as a number; None if it has none."""
    match = LEVEL.search(header)
    if not match:
        return None
    text = match["level"]
    return int(text) if text.isdigit() else roman(text)


def tournament_facts(text):
    """What a tournament hand's text says of its tournament: the buy-in, the level, and the finishes and bounties
    won in the hand. Amounts are cents for a buy-in with a currency, chips otherwise."""
    header = text.split("\n", 1)[0]
    facts = entry(header) or {**NO_ENTRY}
    money = bool(facts["currency"])
    finishes = []
    for match in WON.finditer(text):
        finishes.append({"player": match["player"], "place": 1, "prize": amount(match["prize"], money)})
    for match in FINISHED.finditer(text):
        prize = amount(match["prize"], money) if match["prize"] else None
        finishes.append({"player": match["player"], "place": int(match["place"]), "prize": prize})
    knockouts = [
        {"player": match["player"], "amount": amount(match["amount"], money) or 0, "eliminated": match["eliminated"]}
        for pattern in (BOUNTY, PROGRESSIVE)
        for match in pattern.finditer(text)
    ]
    return {**facts, "level": level(header), "finishes": finishes, "knockouts": knockouts}
