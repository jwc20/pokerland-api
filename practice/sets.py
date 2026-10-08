"""Practice sets: which spots a user plays, how an answer is graded, and what comes back for review.

- **Today's set** mixes spots coming back for review, decisions from the user's own hands, the arithmetic behind
  them, and generated spots to fill it (pokerland-practice-mode.md, 3.1 and 4).
- **Own hands** are at least a day old, so practice never runs alongside a session. The decisions picked first
  are the ones worth studying: those the starter playbook would have played differently, close prices, big pots.
- **Grading** never looks at the card that came. An exact answer counts in full, a rule of thumb at half weight,
  and a reflection not at all (practice.models.Scenario.GRADINGS).
- **Reviews** follow Leitner's boxes: a miss, or "again later", comes back the next day, and each good answer moves
  it a box further away.
"""

import datetime
import random

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from hands.filters import PLAYED
from hands.models import Hand, HandNote
from hands.stats import proportion, streaks
from practice import generators
from practice.models import Attempt, Playbook, Review, Scenario, ScenarioSet, SetItem
from practice.playbook import HOUSE, STARTER
from practice.questions import arithmetic
from practice.rules import evaluate, follows
from practice.spots import POSTFLOP, decisions

DAILY_SIZE = 8
MIN_AGE = datetime.timedelta(days=1)
RECENT_HANDS = 400  # how far back today's set looks for decisions
QUEUED = 6  # added to the interest of a decision in a hand flagged to review: more than any one other reason
# Days until a spot in each Leitner box comes back; out of the last box, it is learnt.
BOXES = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
WEIGHTS = {"exact": 1.0, "reference": 1.0, "rule": 0.5, "reflection": 0.0}
SKILLS = {
    "arithmetic": "Arithmetic",
    "preflop": "Preflop",
    "postflop": "Postflop",
    "push_fold": "Push-or-fold",
    "hand_reading": "Hand reading",
}
# The generated spots that top up today's set, as many from the start of the list as it lacks.
FILL = ["arithmetic", "push_fold", "postflop", "arithmetic", "push_fold", "arithmetic", "postflop", "arithmetic"]
# What practice.generators makes for each skill, by the topics of its spots.
GENERATED = {
    "arithmetic": ("Pot odds, MDF and bluffs", ("equity_needed", "pot_odds", "mdf", "bluff_break_even")),
    "postflop": ("All-in against your draw", ("all_in_call",)),
    "push_fold": ("Push or fold", ("push_fold",)),
}


def house_playbook(key=STARTER["key"]):
    """A house playbook's current version, saved the first time it is used so later versions keep this one."""
    preset = HOUSE[key]
    playbook, _ = Playbook.objects.get_or_create(
        owner=None,
        key=preset["key"],
        version=preset["version"],
        defaults={field: preset[field] for field in ("name", "game", "format", "description", "rules")},
    )
    return playbook


def hand_data(hand):
    """A stored hand as practice.spots reads it: its replay with the columns that go with it."""
    return {
        **hand.replay,
        "hero": hand.hero,
        "game": hand.game,
        "currency": hand.currency,
        "small_blind": hand.small_blind,
        "big_blind": hand.big_blind,
        "tournament_id": hand.tournament_id,
    }


def table_spec(data, step, labels):
    """What the client draws for a decision: the hand up to it, with nobody's cards but the hero's and no results."""
    hero = data["hero"]
    players = [
        {**player, "cards": player["cards"] if player["name"] == hero else [], "won": 0, "net": 0}
        for player in data["players"]
    ]
    hand = {
        "game": data.get("game", "Hold'em No Limit"),
        "currency": data.get("currency", ""),
        "small_blind": data["small_blind"],
        "big_blind": data["big_blind"],
        "ante": data.get("ante", 0),
        "tournament_id": data.get("tournament_id", ""),
        "button_seat": data["button_seat"],
        "max_seats": data.get("max_seats"),
        "hero": hero,
        "players": players,
        "events": data["events"][:step],
    }
    return {"hand": hand, "labels": labels, "revealed": {}}


def legal_of(context):
    """The moves an action question allows, from the decision's context, as practice.table.legal() has them."""
    sizes = context["raise_sizes"]
    return {
        "to_call": context["to_call"],
        "can_check": context["to_call"] == 0,
        "can_raise": sizes is not None,
        "raise_kind": "raise" if context["street"] == "preflop" or context["to_call"] else "bet",
        "min_to": sizes[0] if sizes else None,
        "max_to": sizes[1] if sizes else None,
        "bet": context["in_front"],
        "stack": context["stack"],
    }


def clear(advice):
    """The advice, when a rule settles the decision clearly; else None, and its spot is a reflection."""
    return advice if advice["verdict"] == "clear" and advice["basis"] in ("rule", "exact") else None


def interest(context, rules):
    """How much a decision is worth studying; 0 for one that teaches nothing, such as folding junk first in."""
    if context["street"] == "preflop" and context["move"]["action"] == "fold" and context["facing"] == "none":
        return 0
    score = 1.0
    advice = evaluate(context, rules)
    if clear(advice):
        score += 2 + (0 if follows(advice, context["move"]) else 2)  # a likely mistake is worth most
    if context["equity_needed"] is not None:
        score += 1
        if context["hand_class"] == "draw" and abs(advice["draw_equity"] - context["equity_needed"]) < 0.06:
            score += 1.5  # a close price
    if context["pot_bb"] >= 20:
        score += 1
    if context["street"] in POSTFLOP:
        score += 0.5
    return score


def own_decisions(user, rng, now=None):
    """The user's decisions from their recent hands at least a day old, the most worth studying first.

    Hands the user flagged to review (E1) come in however long ago they were played, and their decisions first.
    Each is (score, hand, data, context); decisions already made into spots are left out.
    """
    now = now or timezone.now()
    rules = house_playbook().rules
    hands = Hand.objects.filter(PLAYED, user=user, played_at__lt=now - MIN_AGE).order_by("-played_at")
    queued = hands.filter(notes__kind=HandNote.Kind.REVIEW, notes__value="to_review")
    recent = list(hands[:RECENT_HANDS])
    flagged = set(queued.values_list("pk", flat=True))
    taken = set(Scenario.objects.filter(owner=user, source="own_hand").values_list("hand_id", "step"))
    found = []
    for hand in [*recent, *queued.exclude(pk__in=[hand.pk for hand in recent])]:
        data = hand_data(hand)
        for context in decisions(data):
            if (hand.pk, context["step"]) in taken:
                continue
            if score := interest(context, rules):
                found.append((score + (QUEUED if hand.pk in flagged else 0) + rng.random(), hand, data, context))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def action_scenario(user, hand, data, context, rules):
    """A spot from one of the user's decisions: what do you do here?"""
    advice = clear(evaluate(context, rules))
    rule = next((card for card in rules if advice and card["id"] == advice["rule"]), None)
    spec = {
        **table_spec(data, context["step"], "names"),
        "question": {"kind": "action", "prompt": "What do you do?"},
        "legal": legal_of(context),
        "panel": True,
    }
    answer = {
        "advice": advice,
        "rule": _card(rule),
        "context": _numbers(context),
        "you_did": context["move"],
        "result": _result(hand, context),
    }
    scenario, _ = Scenario.objects.get_or_create(
        owner=user,
        hand=hand,
        step=context["step"],
        topic="action",
        defaults={
            "source": "own_hand",
            "spec": spec,
            "answer": answer,
            "grading": "rule" if advice else "reflection",
            "skills": ["preflop" if context["street"] == "preflop" else "postflop"],
            "tier": 2 if advice else 1,
        },
    )
    return scenario


def arithmetic_scenario(user, hand, data, context, rng, asked_before=()):
    """A spot from one of the user's decisions that asks for its numbers: the price, MDF, a bluff's odds, M.

    It asks what the set hasn't asked yet, if it can.
    """
    asked = arithmetic(context, data, rng)
    if not asked:
        return None
    fresh = sorted(set(asked) - set(asked_before))
    topic = rng.choice(fresh or sorted(asked))
    spec = {**table_spec(data, context["step"], "names"), "question": asked[topic]["question"], "panel": False}
    scenario, _ = Scenario.objects.get_or_create(
        owner=user,
        hand=hand,
        step=context["step"],
        topic=topic,
        defaults={
            "source": "own_hand",
            "spec": spec,
            "answer": {**asked[topic]["answer"], "context": _numbers(context), "result": _result(hand, context)},
            "grading": "exact",
            "skills": ["arithmetic"],
            "tier": 1 if topic in ("equity_needed", "pot_odds") else 2,
        },
    )
    return scenario


def generated_scenario(skill, rng, asked_before=()):
    """A new generated spot for a skill, saved so everyone's attempts at it add up: a topic not asked yet, if it can."""
    if skill == "arithmetic":
        spot = generators.arithmetic_spot(rng)
        fresh = sorted(set(spot["questions"]) - set(asked_before))
        topic = rng.choice(fresh or sorted(spot["questions"]))
        asked = spot["questions"][topic]
        question, answer, grading, tier = asked["question"], asked["answer"], "exact", 1
    else:
        spot = generators.all_in_spot(rng) if skill == "postflop" else generators.push_fold_spot(rng)
        topic, question, answer, grading, tier = spot["topic"], spot["question"], spot["answer"], "exact", 2
    spec = {**table_spec(spot["hand"], len(spot["hand"]["events"]), "positions"), "question": question}
    spec["revealed"] = spot.get("revealed", {})
    spec["panel"] = question["kind"] == "action"
    if question["kind"] == "action":
        spec["legal"] = legal_of(spot["context"])
    return Scenario.objects.create(
        source="generated",
        topic=topic,
        origin={"generator": topic},
        spec=spec,
        answer={**answer, "context": _numbers(spot["context"])},
        grading=grading,
        skills=[skill],
        tier=tier,
    )


def pooled_scenarios(user, skill, count, rng, exclude=()):
    """Generated spots for a skill the user hasn't tried, other than `exclude`'s: from the pool first, then new ones."""
    tried = Attempt.objects.filter(user=user).values("scenario_id")
    pool = Scenario.objects.filter(source="generated", topic__in=GENERATED[skill][1]).exclude(pk__in=tried)
    found = list(pool.exclude(pk__in=exclude).order_by("?")[:count])
    while len(found) < count:
        found.append(generated_scenario(skill, rng, [scenario.topic for scenario in found]))
    return found


@transaction.atomic
def daily_set(user, day, rng=None):
    """The user's set for `day`, made the first time it is asked for: reviews due, own decisions, then generated."""
    existing = ScenarioSet.objects.filter(user=user, kind="daily", day=day).first()
    if existing:
        return existing
    rng = rng or random.Random()
    chosen = []  # (scenario, review)
    for review in Review.objects.filter(user=user, due__lte=day).select_related("scenario").order_by("due")[:3]:
        chosen.append((review.scenario, True))
    rules = house_playbook().rules
    picked = own_decisions(user, rng)
    actions = [item for item in picked if item[3]["street"] in POSTFLOP or item[0] >= 3][:3]
    for _, hand, data, context in actions:
        chosen.append((action_scenario(user, hand, data, context, rules), False))
    for _, hand, data, context in [item for item in picked if item not in actions][:2]:
        asked_before = [scenario.topic for scenario, _ in chosen]
        if scenario := arithmetic_scenario(user, hand, data, context, rng, asked_before):
            chosen.append((scenario, False))
    fill = FILL[: max(0, DAILY_SIZE - len(chosen))]
    for skill in dict.fromkeys(fill):
        taken = {scenario.pk for scenario, _ in chosen}
        chosen += [(scenario, False) for scenario in pooled_scenarios(user, skill, fill.count(skill), rng, taken)]
    return _save_set(user, "daily", day, chosen)


@transaction.atomic
def mode_set(user, kind, day, skill="", rng=None):
    """A set of one mode: decisions from the user's own hands, or generated spots for one skill."""
    rng = rng or random.Random()
    if kind == "my_hands":
        rules = house_playbook().rules
        chosen = []
        for _, hand, data, context in own_decisions(user, rng)[:DAILY_SIZE]:
            chosen.append((action_scenario(user, hand, data, context, rules), False))
    else:
        chosen = [(scenario, False) for scenario in pooled_scenarios(user, skill, DAILY_SIZE, rng)]
    return _save_set(user, kind, day, chosen, skill)


def _save_set(user, kind, day, chosen, skill=""):
    practice_set = ScenarioSet.objects.create(user=user, kind=kind, day=day, skill=skill)
    seen = set()
    position = 0
    for scenario, review in chosen:
        if scenario.pk in seen:
            continue
        seen.add(scenario.pk)
        SetItem.objects.create(set=practice_set, scenario=scenario, position=position, review=review)
        position += 1
    return practice_set


def grade(scenario, data):
    """How an answer to a scenario is graded: {"grade", "score", "weight", "ev_lost_bb", "rule"}.

    `data` is the attempt: a `choice`, or an `action` with the `amount` a bet or raise makes the bet.
    """
    answer = scenario.answer
    weight = WEIGHTS[scenario.grading]
    if scenario.spec["question"]["kind"] == "choice":
        right = data.get("choice") == answer["correct"]
        return {"grade": "good" if right else "poor", "score": float(right), "weight": weight}
    action = data["action"]
    if scenario.grading == "exact":
        values = answer["ev_bb"]
        chosen = values.get(_as_answered(action), min(values.values()))
        lost = round(max(values.values()) - chosen, 2)
        right = _as_answered(action) in answer["best"]
        return {"grade": "good" if right else "poor", "score": float(right), "weight": weight, "ev_lost_bb": lost}
    if scenario.grading == "rule" and answer.get("advice"):
        move = attempted_move(scenario, data)
        advice = answer["advice"]
        if follows(advice, move):
            grade_, score = "good", 1.0
        elif move["action"] in advice["accepts"]:
            grade_, score = "acceptable", 0.5  # the right action at a size the card doesn't ask for
        else:
            grade_, score = "poor", 0.0
        return {"grade": grade_, "score": score, "weight": weight, "rule": advice["rule"] or ""}
    return {"grade": "ungraded", "score": None, "weight": 0.0}


def _as_answered(action):
    """An all-in answer is a raise; the answer keys bets and raises alike as "raise"."""
    return "raise" if action == "bet" else action


def attempted_move(scenario, data):
    """An attempt's move as practice.spots describes one: its action and, for a bet, its share of the pot."""
    move = {"action": data["action"]}
    numbers = scenario.answer.get("context", {})
    amount = data.get("amount")
    if data["action"] in ("bet", "raise") and amount and numbers.get("pot"):
        move["size"] = round((amount - numbers.get("in_front", 0)) / numbers["pot"], 3)
    return move


@transaction.atomic
def record(user, scenario, practice_set, data, today):
    """Grades and saves an attempt, and moves the spot through its review boxes."""
    graded = grade(scenario, data)
    attempt = Attempt.objects.create(
        user=user,
        scenario=scenario,
        set=practice_set,
        choice=data.get("choice"),
        action=data.get("action", ""),
        amount=data.get("amount"),
        reason=data.get("reason", ""),
        confidence=data.get("confidence"),
        time_taken=data.get("time_taken"),
        grade=graded["grade"],
        score=graded["score"],
        weight=graded["weight"],
        ev_lost_bb=graded.get("ev_lost_bb"),
        rule=graded.get("rule", ""),
    )
    review = Review.objects.filter(user=user, scenario=scenario).first()
    if graded["grade"] == "poor":
        again_later(user, scenario, today)
    elif review and graded["grade"] == "good":
        if review.box >= max(BOXES):
            review.delete()  # learnt
        else:
            review.box += 1
            review.due = today + datetime.timedelta(days=BOXES[review.box])
            review.save()
    if practice_set and not practice_set.finished:
        answered = Attempt.objects.filter(set=practice_set).values("scenario").distinct().count()
        if answered >= practice_set.items.count():
            practice_set.finished = timezone.now()
            practice_set.save(update_fields=["finished"])
    return attempt


def again_later(user, scenario, today):
    """Puts a spot back in the first box: it comes back tomorrow."""
    Review.objects.update_or_create(
        user=user, scenario=scenario, defaults={"box": 1, "due": today + datetime.timedelta(days=BOXES[1])}
    )


def skill_scores(user):
    """Each skill's weighted share of good answers with its 95% Wilson range, as the My game tiles show theirs.

    A rule of thumb counts at half weight and a reflection not at all, so `could` can be less than `attempts`.
    """
    rows = _skill_rows(user)
    scores = []
    for skill, label in SKILLS.items():
        row = rows.get(skill, {"attempts": 0, "good": 0.0, "total": 0.0})
        share = proportion(row["good"], row["total"]) if row["total"] else proportion(0, 0)
        scores.append({"skill": skill, "label": label, "attempts": row["attempts"], **_rounded(share)})
    return scores


def _skill_rows(user):
    rows = {}
    for skills, weight, score in Attempt.objects.filter(user=user).values_list("scenario__skills", "weight", "score"):
        for skill in skills:
            row = rows.setdefault(skill, {"attempts": 0, "good": 0.0, "total": 0.0})
            row["attempts"] += 1
            if weight and score is not None:
                row["good"] += weight * score
                row["total"] += weight
    return rows


def _rounded(share):
    """A proportion over weighted counts: the counts to a tenth, as the weights are halves."""
    return {**share, "did": round(share["did"], 1), "could": round(share["could"], 1)}


def practice_days(user, tz):
    """The days in `tz` the user answered spots on, with how many, oldest first; and the streak they make."""
    days = list(
        Attempt.objects.filter(user=user)
        .annotate(day=TruncDate("created", tzinfo=tz))
        .values("day")
        .annotate(attempts=Count("id"))
        .order_by("day")
    )
    today = timezone.localdate(timezone=tz)
    current, best = streaks([day["day"] for day in days], today)
    return {"days": days, "current_streak": current, "best_streak": best, "today": today}


def _result(hand, context):
    """Where the decision is in the user's hand, for its replay, and how the hand went."""
    return {"hand": hand.pk, "step": context["step"], "net_bb": round(hand.hero_net / hand.big_blind, 2)}


def _card(rule):
    """A rule card as the feedback quotes it."""
    if not rule:
        return None
    return {key: rule.get(key) for key in ("id", "number", "family", "rule", "why", "scope", "source")}


def _numbers(context):
    """The numbers the feedback card and grading need from a context, without the cards to come."""
    keys = (
        "street", "facing", "bettor", "bet", "pot_before", "to_call", "pot", "pot_if_call", "equity_needed", "mdf",
        "effective_bb", "spr", "players", "position", "hand_class", "made", "draws", "in_front", "big_blind",
    )
    return {key: context.get(key) for key in keys}
