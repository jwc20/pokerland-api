"""By the book: how often a user's own hands kept each of a playbook's rules (pokerland-practice-mode-additional.md, 7).

The rule engine (practice.rules) runs over the user's stored hands, at least a day old, as it runs at a practice
table: "Out of position after calling a raise, you bet into the raiser 14 of 61 times." Each rule becomes a leak
detector, and the decisions that broke one are spots worth practising.
"""

from django.utils import timezone

from hands.filters import PLAYED
from hands.models import Hand
from hands.stats import proportion
from practice.rules import check
from practice.sets import MIN_AGE, hand_data
from practice.spots import decisions

# How far back by the book looks: enough hands to say something, few enough for a request.
RECENT_HANDS = 1000


def by_the_book(user, rules, now=None):
    """Each default rule's chances in the user's recent hands, kept or not: {rule id: [(hand, context, kept)]}."""
    now = now or timezone.now()
    hands = Hand.objects.filter(PLAYED, user=user, played_at__lt=now - MIN_AGE).order_by("-played_at")
    found = {rule["id"]: [] for rule in rules if not rule.get("adjustment")}
    for hand in hands[:RECENT_HANDS]:
        for context in decisions(hand_data(hand)):
            for result in check(context, context["move"], rules):
                found[result["rule"]].append((hand, context, result["followed"]))
    return found


def summarise(found):
    """Each rule's share kept, with its 95% Wilson range, from by_the_book's chances."""
    return [
        {"rule": rule_id, **proportion(sum(kept for _, _, kept in chances), len(chances))}
        for rule_id, chances in found.items()
    ]


def listed(chances):
    """One rule's chances from by_the_book, newest first: where each was, what was done, and whether it was kept."""
    return [
        {
            "hand": hand.pk,
            "hand_id": hand.hand_id,
            "played_at": hand.played_at,
            "step": context["step"],
            "street": context["street"],
            "move": context["move"],
            "followed": kept,
        }
        for hand, context, kept in chances
    ]
