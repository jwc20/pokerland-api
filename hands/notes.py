"""What users write on their hands (FND-7 and E1 of the feature ideas): notes, tags, the review queue, and why
they bet.

"If you can't say why you bet, maybe you shouldn't be betting" [JHU 5]: each of the hero's bets and raises can
carry a purpose, and `purpose_stats` shows how the bets of each purpose went. A purpose is keyed by which of the
hero's bets and raises it is for, counted by `bets`, which also says what came of each one.
"""

from collections import defaultdict

from django.db.models import Count, OuterRef, Subquery

from hands.models import Hand, HandNote
from hands.stats import proportion, with_hero_all_in

REVIEW_STATES = ("to_review", "reviewed")
# Why a bet or raise was made: for value, as a bluff, as a semi-bluff (a bluff with outs), to protect a hand that
# is likely best, to keep the pot small, or as a small bet out of position that sets the price of the street.
PURPOSES = ("value", "bluff", "semi_bluff", "protection", "pot_control", "blocking")
# Tags the notes panel offers before the user has any of their own [JHU 4; MIT 2].
SUGGESTED_TAGS = ("cooler", "misclick", "tilt", "ask a coach")
NOTE_STREETS = ("", "preflop", "flop", "turn", "river")  # empty for a note on the whole hand
STREET_ORDER = ("preflop", "flop", "turn", "river")
TAG_LENGTH = 32
NOTE_LENGTH = 2000
WRITEUP_LENGTH = 20000  # a hand written up to show others (E2), street by street
QUEUE_LENGTH = 5  # the review queue's hands that /api/review/ lists
OUTCOMES = ("folded", "called", "raised")


def bets(events, player):
    """`player`'s bets and raises in a hand's replay events, in the order made.

    Each has its street, the chips put in with it, everything in the middle
    before it (the pot and the bets in front of the players), and its outcome
    before the street ended or the player acted again: "folded" when nobody
    called or raised it, else "called" or "raised".
    """
    middle = 0
    found = []
    answering = None  # the player's last bet or raise, while the others answer it
    for event in events:
        kind = event["type"]
        if kind == "street":
            answering = None
        elif kind == "return":
            middle -= event["amount"]
        elif kind in ("post", "fold", "check", "call", "bet", "raise"):
            if event.get("player") == player:
                answering = None
                if kind in ("bet", "raise"):
                    answering = {
                        "street": event["street"],
                        "amount": event["amount"],
                        "pot_before": middle,
                        "outcome": "folded",
                    }
                    found.append(answering)
            elif answering and kind == "raise":
                answering["outcome"] = "raised"
            elif answering and kind == "call" and answering["outcome"] == "folded":
                answering["outcome"] = "called"
            middle += event.get("amount", 0)
    return found


def save_note(user, hand, data):
    """Adds the note `data` describes to `hand`, or changes the one it takes the place of: the street's note, the
    same tag, the review state, or the bet's purpose. Returns (note, created)."""
    kind = data["kind"]
    if kind == HandNote.Kind.NOTE:
        identity = {"street": data["street"]}
    elif kind == HandNote.Kind.TAG:
        identity = {"value": data["value"]}
    elif kind == HandNote.Kind.PURPOSE:
        identity = {"bet": data["bet"]}
    else:
        identity = {}
    fields = {name: data[name] for name in ("street", "value", "text") if name in data and name not in identity}
    return HandNote.objects.update_or_create(user=user, hand=hand, kind=kind, **identity, defaults=fields)


def review_summary(user):
    """The user's review queue: how many hands wait and how many are done, the latest flagged, and their tags."""
    reviews = HandNote.objects.filter(user=user, kind=HandNote.Kind.REVIEW)
    counts = dict.fromkeys(REVIEW_STATES, 0) | dict(
        reviews.values("value").annotate(hands=Count("id")).values_list("value", "hands").order_by()
    )
    flagged = reviews.filter(hand=OuterRef("pk")).values("updated")[:1]
    queue = (
        with_hero_all_in(Hand.objects.filter(user=user, notes__kind=HandNote.Kind.REVIEW, notes__value="to_review"))
        .defer("replay", "facts", "phh")
        .annotate(flagged=Subquery(flagged))
        .order_by("-flagged", "-id")[:QUEUE_LENGTH]
    )
    tags = (
        HandNote.objects.filter(user=user, kind=HandNote.Kind.TAG)
        .values("value")
        .annotate(hands=Count("id"))
        .order_by("-hands", "value")
    )
    return {
        "to_review": counts["to_review"],
        "reviewed": counts["reviewed"],
        "queue": list(queue),
        "tags": [{"tag": row["value"], "hands": row["hands"]} for row in tags],
        "suggested_tags": list(SUGGESTED_TAGS),
    }


def purpose_stats(user, hands):
    """How the hero's bets and raises in `hands` went, by the purpose the user gave them and by street.

    Each group counts its bets, how often they took the pot at once (nobody
    called or raised), how often they were called or raised, their average
    size as a share of the pot, and the share of folds a pure bluff of that size
    needs to break even: size ÷ (1 + size).
    """
    notes = HandNote.objects.filter(user=user, kind=HandNote.Kind.PURPOSE, hand__in=hands).select_related("hand")
    groups = defaultdict(lambda: {"bets": 0, **dict.fromkeys(OUTCOMES, 0), "sizes": []})
    made = {}
    for note in notes.order_by("hand_id", "bet"):
        hand = note.hand
        if hand.pk not in made:
            made[hand.pk] = bets(hand.replay.get("events", []), hand.hero) if hand.hero else []
        if note.bet >= len(made[hand.pk]):
            continue  # the hand no longer has that bet, as a parser may have read it otherwise
        bet = made[hand.pk][note.bet]
        group = groups[note.value, bet["street"]]
        group["bets"] += 1
        group[bet["outcome"]] += 1
        if bet["pot_before"] > 0:
            group["sizes"].append(bet["amount"] / bet["pot_before"])

    def order(key):
        purpose, street = key
        return (PURPOSES.index(purpose), STREET_ORDER.index(street) if street in STREET_ORDER else len(STREET_ORDER))

    rows = []
    for (purpose, street), group in sorted(groups.items(), key=lambda item: order(item[0])):
        size = sum(group["sizes"]) / len(group["sizes"]) if group["sizes"] else None
        rows.append(
            {
                "purpose": purpose,
                "street": street,
                "bets": group["bets"],
                "took_pot": proportion(group["folded"], group["bets"]),
                "called": group["called"],
                "raised": group["raised"],
                "size": None if size is None else round(size, 3),
                "needed": None if size is None else round(size / (1 + size), 3),
            }
        )
    return rows
