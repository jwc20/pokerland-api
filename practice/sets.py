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

from hands import ranges
from hands.filters import PLAYED
from hands.models import Hand, HandNote
from hands.stats import proportion, streaks
from leagues import classes
from practice import charts, generators, library, ratings
from practice.models import Attempt, Playbook, Review, Scenario, ScenarioSet, SetItem, SkillScore
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
FILL = ["arithmetic", "preflop", "push_fold", "postflop", "hand_reading", "arithmetic", "preflop", "push_fold"]
# What practice.generators makes for each skill, by the topics of its spots.
GENERATED = {
    "arithmetic": ("Pot odds, MDF and bluffs", ("equity_needed", "pot_odds", "mdf", "bluff_break_even")),
    "preflop": ("Opening ranges", ("preflop_open", "preflop_facing")),
    "postflop": ("All-in against your draw", ("all_in_call",)),
    "push_fold": ("Push or fold", ("push_fold",)),
    "hand_reading": ("Ranges from a line", ("range_read",)),
}
# The generators each skill's spots come from, other than arithmetic's, and how they are graded.
GENERATORS = {
    "preflop": (generators.preflop_spot, "reference"),
    "postflop": (generators.all_in_spot, "exact"),
    "push_fold": (generators.push_fold_spot, "exact"),
    "hand_reading": (generators.range_read_spot, "reference"),
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
    """What the client draws for a decision: the hand up to it, with nobody's cards but the hero's and no results.

    The hero may be any player whose cards are known, as in their seat: then theirs are dealt face up, not those of
    the hand's own hero.
    """
    hero = data["hero"]
    players = [
        {**player, "cards": player["cards"] if player["name"] == hero else [], "won": 0, "net": 0}
        for player in data["players"]
    ]
    own = next((player["cards"] for player in players if player["name"] == hero), [])
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
        "events": dealt_to(data["events"][:step], hero, own),
    }
    return {"hand": hand, "labels": labels, "revealed": {}}


def outcome_of(data, step, hero):
    """The whole hand from the seat a spot was asked from, for once it is answered: what was played there, and how the
    hand ended. Up to the decision, the events are the spot's own; then every one after it, from the move made at the
    table to the showdown's cards and who collected. Each player has their result.

    {"hand": the hand as TableHandSerializer has it, "decision": the replay step the spot asked at}.
    """
    spot = table_spec({**data, "hero": hero}, step, "names")["hand"]
    results = {player["name"]: player for player in data["players"]}
    players = [
        {**player, "won": results[player["name"]].get("won", 0), "net": results[player["name"]].get("net", 0)}
        for player in spot["players"]
    ]
    events = [*spot["events"], *data["events"][step:]]
    return {"hand": {**spot, "players": players, "events": events}, "decision": len(spot["events"])}


def dealt_to(events, hero, cards):
    """The events with `hero`'s cards the only ones dealt face up: the replay shows a seat's cards from its deal."""
    kept = [event for event in events if event["type"] != "deal" or event.get("player") == hero]
    if cards and not any(event["type"] == "deal" for event in kept):
        at = next((i for i, event in enumerate(kept) if event["type"] != "post"), len(kept))
        kept.insert(at, {"type": "deal", "street": "preflop", "player": hero, "cards": list(cards)})
    return kept


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
        "rule": quoted_card(rule),
        "context": numbers_of(context),
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
            "answer": {**asked[topic]["answer"], "context": numbers_of(context), "result": _result(hand, context)},
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
        make, grading = GENERATORS[skill]
        spot = make(rng)
        topic, question, answer, tier = spot["topic"], spot["question"], spot["answer"], spot.get("tier", 2)
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
        answer={**answer, "context": numbers_of(spot["context"])},
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
    due = Review.objects.filter(user=user, due__lte=day).select_related("scenario").order_by("due")
    live = set()
    if due.filter(scenario__source="shared").exists():
        live = {share.hand_id for _, share in classes.shared_hands(user)}
    # A spot from a hand withdrawn from the user's classes, or whose share was revoked, doesn't come back.
    kept = [review for review in due[:30] if review.scenario.source != "shared" or review.scenario.hand_id in live]
    for review in kept[:3]:
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
    return save_set(user, "daily", day, chosen)


@transaction.atomic
def mode_set(user, kind, day, skill="", rng=None):
    """A set of one mode: decisions from the user's own hands, generated spots for one skill, or the library."""
    rng = rng or random.Random()
    if kind == "my_hands":
        rules = house_playbook().rules
        chosen = []
        for _, hand, data, context in own_decisions(user, rng)[:DAILY_SIZE]:
            chosen.append((action_scenario(user, hand, data, context, rules), False))
    elif kind == "library":
        chosen = [(scenario, False) for scenario in library_picks(user, rng)]
    else:
        chosen = [(scenario, False) for scenario in pooled_scenarios(user, skill, DAILY_SIZE, rng)]
    return save_set(user, kind, day, chosen, skill)


def library_scenarios():
    """The library's spots (practice.library), each saved the first time it is asked for so everyone's attempts at it
    add up. A new version of the library saves new spots, and the old ones keep their attempts."""
    saved = {
        scenario.origin["library"]: scenario
        for scenario in Scenario.objects.filter(source="library", origin__version=library.VERSION)
    }
    for key in library.ENTRIES:
        if key not in saved:
            saved[key] = library_scenario(library.build(key))
    return [saved[key] for key in library.ENTRIES]


def library_scenario(entry):
    """Saves one library entry as a spot: at its table, or with no table and its setup in words."""
    question = entry["question"]
    if entry["hand"]:
        spec = {**table_spec(entry["hand"], len(entry["hand"]["events"]), "positions"), "question": question}
        spec["panel"] = question["kind"] == "action"
        if question["kind"] == "action":
            spec["legal"] = legal_of(entry["context"])
    else:
        spec = {"hand": None, "labels": "positions", "revealed": {}, "question": question, "panel": False}
    spec.update(setup=entry["setup"], title=entry["title"], credit=entry["source"])
    answer = dict(entry["answer"])
    if entry["context"]:
        answer["context"] = numbers_of(entry["context"])
    return Scenario.objects.create(
        source="library",
        topic=entry["topic"],
        origin={"library": entry["key"], "version": library.VERSION},
        spec=spec,
        answer=answer,
        grading=entry["grading"],
        skills=entry["skills"],
        tier=entry["tier"],
    )


def library_picks(user, rng, count=DAILY_SIZE):
    """Library spots for a set: those the user hasn't tried first, then the ones they last missed, then the rest."""
    spots = library_scenarios()
    last = {}
    for attempt in Attempt.objects.filter(user=user, scenario__in=spots).order_by("created"):
        last[attempt.scenario_id] = attempt.grade
    groups = (
        [spot for spot in spots if spot.pk not in last],
        [spot for spot in spots if last.get(spot.pk) in ("poor", "acceptable")],
        [spot for spot in spots if last.get(spot.pk) in ("good", "ungraded")],
    )
    for group in groups:
        rng.shuffle(group)
    return [spot for group in groups for spot in group][:count]


def save_set(user, kind, day, chosen, skill=""):
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

    `data` is the attempt: a `choice`, a `hand_range` in range notation, or an `action` with the `amount` a bet or
    raise makes the bet. A range earns partial credit, its overlap with the stated range (practice.charts).
    """
    answer = scenario.answer
    weight = WEIGHTS[scenario.grading]
    kind = scenario.spec["question"]["kind"]
    if kind == "choice":
        right = data.get("choice") == answer["correct"]
        return {"grade": "good" if right else "poor", "score": float(right), "weight": weight}
    if kind == "range":
        score = charts.overlap_score(ranges.parse(data["hand_range"]), ranges.parse(answer["range"]))
        return {"grade": charts.range_grade(score), "score": round(score, 3), "weight": weight}
    action = data["action"]
    if scenario.grading == "reference":
        chosen = _as_answered(action)
        if chosen in answer["best"]:
            return {"grade": "good", "score": 1.0, "weight": weight}
        if chosen in answer.get("acceptable", ()):
            return {"grade": "acceptable", "score": 0.5, "weight": weight}
        return {"grade": "poor", "score": 0.0, "weight": weight}
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
        hand_range=data.get("hand_range", ""),
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
    rate(attempt)
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
    # A test ends after its planned spots (practice.aptitude); any other set once each of its spots is answered.
    if practice_set and not practice_set.finished:
        answered = Attempt.objects.filter(set=practice_set).values("scenario").distinct().count()
        if answered >= (practice_set.planned or practice_set.items.count()):
            practice_set.finished = timezone.now()
            practice_set.save(update_fields=["finished"])
    return attempt


def rate(attempt, now=None):
    """After a graded answer, the user's rating in each of the spot's skills and the spot's difficulty
    (practice.ratings). A reflection, which isn't graded, changes neither."""
    if attempt.score is None or not attempt.weight:
        return
    now = now or attempt.created
    scenario = Scenario.objects.select_for_update().get(pk=attempt.scenario_id)
    difficulty = scenario.difficulty if scenario.difficulty is not None else ratings.first_difficulty(scenario.tier)
    spread = scenario.difficulty_deviation or ratings.START_DEVIATION
    users = []
    for skill in scenario.skills:
        score, _ = SkillScore.objects.select_for_update().get_or_create(
            user_id=attempt.user_id, skill=skill, defaults={"updated": now}
        )
        days = (now - score.updated).total_seconds() / 86400
        before = (score.rating, ratings.widened(score.deviation, days))
        score.rating, score.deviation = ratings.update(*before, difficulty, spread, attempt.score, attempt.weight)
        score.attempts += 1
        score.updated = now
        score.save()
        users.append(before)
    if users:  # the spot learns from the user's rating in its first skill, as it stood
        rating, deviation = users[0]
        scenario.difficulty, scenario.difficulty_deviation = ratings.update(
            difficulty, spread, rating, deviation, 1 - attempt.score, attempt.weight
        )
        scenario.rated += 1
        scenario.save(update_fields=["difficulty", "difficulty_deviation", "rated"])


@transaction.atomic
def rebuild_ratings():
    """Every rating afresh, from every graded answer in the order they were given: after changing practice.ratings,
    or for answers given before there were ratings."""
    SkillScore.objects.all().delete()
    Scenario.objects.update(difficulty=None, difficulty_deviation=None, rated=0)
    count = 0
    for attempt in Attempt.objects.order_by("created", "id").iterator():
        if attempt.score is not None and attempt.weight:
            rate(attempt)
            count += 1
    return count


def skill_ratings(user, now=None):
    """Each of the user's skill ratings as it stands now, its range widened by any time away:
    {skill: {"rating", "deviation", "low", "high", "attempts"}}."""
    return _ratings_of([user.pk], now).get(user.pk, {})


def _ratings_of(user_ids, now=None):
    """skill_ratings for several users, in one query: {user id: ratings}."""
    now = now or timezone.now()
    found = {}
    for score in SkillScore.objects.filter(user_id__in=user_ids):
        deviation = ratings.widened(score.deviation, (now - score.updated).total_seconds() / 86400)
        low, high = ratings.interval(score.rating, deviation)
        found.setdefault(score.user_id, {})[score.skill] = {
            "rating": round(score.rating),
            "deviation": round(deviation),
            "low": round(low),
            "high": round(high),
            "attempts": score.attempts,
        }
    return found


def again_later(user, scenario, today):
    """Puts a spot back in the first box: it comes back tomorrow."""
    Review.objects.update_or_create(
        user=user, scenario=scenario, defaults={"box": 1, "due": today + datetime.timedelta(days=BOXES[1])}
    )


def skill_scores(user):
    """Each skill's weighted share of good answers with its 95% Wilson range, as the My game tiles show theirs, and
    its rating (practice.ratings), shown once its range is narrow enough.

    A rule of thumb counts at half weight and a reflection not at all, so `could` can be less than `attempts`.
    """
    return skill_scores_of([user.pk])[user.pk]


def skill_scores_of(user_ids):
    """skill_scores for several users, as a class's coaches see them, in two queries: {user id: scores}."""
    rows, rated = _skill_rows(user_ids), _ratings_of(user_ids)
    return {user_id: _scores(rows.get(user_id, {}), rated.get(user_id, {})) for user_id in user_ids}


def _scores(rows, rated):
    scores = []
    for skill, label in SKILLS.items():
        row = rows.get(skill, {"attempts": 0, "good": 0.0, "total": 0.0})
        share = proportion(row["good"], row["total"]) if row["total"] else proportion(0, 0)
        rating = rated.get(skill)
        shown = rating if rating and rating["deviation"] <= ratings.SHOWN_DEVIATION else None
        scores.append({"skill": skill, "label": label, "attempts": row["attempts"], **_rounded(share), "rating": shown})
    return scores


def _skill_rows(user_ids):
    """Each user's answers by skill: {user id: {skill: {"attempts", "good", "total"}}}."""
    rows = {}
    attempts = Attempt.objects.filter(user_id__in=user_ids)
    for user_id, skills, weight, score in attempts.values_list("user_id", "scenario__skills", "weight", "score"):
        for skill in skills:
            row = rows.setdefault(user_id, {}).setdefault(skill, {"attempts": 0, "good": 0.0, "total": 0.0})
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


def quoted_card(rule):
    """A rule card as the feedback quotes it."""
    if not rule:
        return None
    return {key: rule.get(key) for key in ("id", "number", "family", "rule", "why", "scope", "source")}


def numbers_of(context):
    """The numbers the feedback card and grading need from a context, without the cards to come."""
    keys = (
        "street", "facing", "bettor", "bet", "pot_before", "to_call", "pot", "pot_if_call", "equity_needed", "mdf",
        "effective_bb", "spr", "players", "position", "hand_class", "made", "draws", "in_front", "big_blind",
    )
    return {key: context.get(key) for key in keys}
