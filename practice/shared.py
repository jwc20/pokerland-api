"""Shared hands (pokerland-practice-mode.md, 4.3): decisions from hands shared with the user's classes (leagues), played
from the sharer's seat.

Only hands their owner shared with a class are used, always anonymized: players by position, the sharer as "Hero",
no table or number (hands.shares.anonymized). A withdrawn hand, or one whose share was revoked, leaves future sets;
spots already answered keep their attempts. A spot belongs to no one, like a generated one, so everyone's answers
teach its difficulty; who may answer it is checked against their classes (leagues.classes.can_practise).
"""

import random

from django.db import transaction
from django.utils import timezone

from hands.shares import anonymized
from leagues import classes
from practice.models import Scenario
from practice.rules import evaluate
from practice.sets import (
    DAILY_SIZE,
    MIN_AGE,
    clear,
    hand_data,
    house_playbook,
    interest,
    legal_of,
    numbers_of,
    quoted_card,
    save_set,
    table_spec,
)
from practice.spots import decisions

PER_HAND = 3  # decisions from any one hand, so a set isn't one hand
ANSWERED_WEIGHT = 0.25  # a spot the user has answered counts this much of its interest, so new ones come first


def open_to(user, scenario):
    """Whether the user may answer a spot: their own, a shared-by-nobody one (generated, the library), or one from a
    hand shared with their classes, still live or already in one of their sets."""
    if scenario.owner_id is not None:
        return scenario.owner_id == user.pk
    if scenario.source != "shared":
        return True
    return classes.can_practise(user, scenario.hand_id) or scenario.sets.filter(user=user).exists()


def action_scenario(assignment, share, data, context, rules):
    """A spot from a decision in a shared hand: what would you do in their seat?"""
    hand = share.hand
    advice = clear(evaluate(context, rules))
    rule = next((card for card in rules if advice and card["id"] == advice["rule"]), None)
    sharer = share.user.username
    spec = {
        **table_spec(data, context["step"], "names"),
        "question": {
            "kind": "action",
            "prompt": f"{sharer} shared this hand with {assignment.league.name}. What do you do?",
        },
        "legal": legal_of(context),
        "panel": True,
        "credit": f"Shared by {sharer}",
    }
    answer = {
        "advice": advice,
        "rule": quoted_card(rule),
        "context": numbers_of(context),
        "player": sharer,
        "they_did": context["move"],
        # The hand isn't the user's, so there's no replay to open: only how it went.
        "result": {"hand": None, "step": context["step"], "net_bb": round(hand.hero_net / hand.big_blind, 2)},
    }
    scenario, _ = Scenario.objects.get_or_create(
        owner=None,
        hand=hand,
        step=context["step"],
        topic="shared_action",
        defaults={
            "source": "shared",
            "origin": {"share": share.pk},
            "spec": spec,
            "answer": answer,
            "grading": "rule" if advice else "reflection",
            "skills": ["preflop" if context["street"] == "preflop" else "postflop"],
            "tier": 2 if advice else 1,
        },
    )
    return scenario


def picks(user, rng, count=DAILY_SIZE):
    """Spots from the hands shared with the user's classes: the most worth studying first, new ones before answered
    ones, and no more than PER_HAND from a hand."""
    rules = house_playbook().rules
    answered = set(
        Scenario.objects.filter(source="shared", attempts__user=user).values_list("hand_id", "step").distinct()
    )
    found = []
    played_before = timezone.now() - MIN_AGE
    for assignment, share in classes.shared_hands(user):
        if share.hand.played_at >= played_before:
            continue  # nothing live: a hand comes into practice a day after it was played, as the user's own do
        data = hand_data(anonymized(share.hand))
        scored = []
        for context in decisions(data):
            if score := interest(context, rules):
                if (share.hand_id, context["step"]) in answered:
                    score *= ANSWERED_WEIGHT
                scored.append((score + rng.random(), assignment, share, data, context))
        scored.sort(key=lambda item: item[0], reverse=True)
        found += scored[:PER_HAND]
    found.sort(key=lambda item: item[0], reverse=True)
    return [
        action_scenario(assignment, share, data, context, rules)
        for _, assignment, share, data, context in found[:count]
    ]


@transaction.atomic
def shared_set(user, day, rng=None):
    """A set of spots from the hands shared with the user's classes."""
    rng = rng or random.Random()
    return save_set(user, "shared", day, [(scenario, False) for scenario in picks(user, rng)])
