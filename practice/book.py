"""By the book: how often a user's own hands kept each of a playbook's rules (pokerland-practice-mode-additional.md, 7).

The rule engine (practice.rules) runs over the user's stored hands, at least a day old, as it runs at a practice
table: "Out of position after calling a raise, you bet into the raiser 14 of 61 times." Each rule becomes a leak
detector, and the decisions that broke one are spots worth practising.

Reading a thousand hands takes a while, so `report` keeps what it found (hands.results) until the user's data changes
or one more of their hands turns a day old.
"""

from django.utils import timezone

from hands import results
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
    hands = Hand.objects.filter(PLAYED, user=user, played_at__lt=now - MIN_AGE).order_by("-played_at", "-id")
    found = {rule["id"]: [] for rule in rules if not rule.get("adjustment")}
    for hand in hands[:RECENT_HANDS]:
        for context in decisions(hand_data(hand)):
            for result in check(context, context["move"], rules):
                found[result["rule"]].append((hand, context, result["followed"]))
    return found


def report(user, playbook, rule=None, now=None):
    """By the book for a playbook, as BookSerializer has it: how many hands were read, each default rule's share
    kept, and with `rule` the decisions it applied to.

    Kept until the user's data changes or another of their hands turns a day old, which `newest` (the latest hand
    old enough) stands for. One reading keeps every rule's decisions, so asking for another rule's finds them kept.
    """
    now = now or timezone.now()
    old_enough = Hand.objects.filter(PLAYED, user=user, played_at__lt=now - MIN_AGE)
    newest = old_enough.order_by("-played_at", "-id").values_list("pk", flat=True).first()
    asked = {"playbook": playbook.pk, "newest": newest}
    summary_key = results.key_of("book", asked)

    def chances_key(rule_id):
        return results.key_of("book.chances", {**asked, "rule": rule_id})

    wanted = [summary_key, *([chances_key(rule)] if rule else [])]
    found = results.lookup(user.pk, wanted)
    if not all(key in found for key in wanted):
        version = results.version_of(user.pk)  # before the reading, as hands.results.remembered does
        chances = by_the_book(user, playbook.rules, now)
        answers = {
            summary_key: {"hands": min(old_enough.count(), RECENT_HANDS), "rules": summarise(chances)},
            **{chances_key(rule_id): listed(rows) for rule_id, rows in chances.items()},
        }
        results.keep(user.pk, version, answers)
        found = {key: results.plain(value) for key, value in answers.items()}
    data = dict(found[summary_key])
    if rule:
        data["chances"] = found[chances_key(rule)]
    return data


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
