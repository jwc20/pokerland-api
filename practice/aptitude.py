"""The aptitude test (pokerland-practice-mode.md, 3.5 and 6): 24 graded spots, about twelve minutes, that measure how
well you decide, skill by skill.

- **Graded kinds only**: exact, reference ranges and rules of thumb. A reflection has no answer to check, so it never
  comes up.
- **Adaptive.** The first spots probe every skill that has spots to ask. After that each spot goes where the test's
  score is least certain: the skill with the widest 95% range so far, the one with the fewest spots on a tie. Within
  the skill it is the spot, among those you haven't seen, whose difficulty is nearest your rating (practice.ratings),
  where an answer says most.
- **Answers stay on the server until the test ends**: no grade, no answer, no explanation until the last spot.
- **Fresh spots.** A spot you have answered before, anywhere, isn't asked again while there are others; generated
  skills make new ones when their pool runs dry. Misses still come back in the daily sets, never in tests.

The report shows each skill's accuracy in the test with its range, the ratings as they stood when it ended, every
spot with your answer and the reference one, strengths and gaps in words with the sample behind each, and what to
practise next: the weakest skill whose range is narrow enough to trust. Until the score is shown to predict results
at the table, it claims only how well you decided in these spots.
"""

import random

from django.db import transaction
from django.utils import timezone

from hands.stats import proportion
from practice import ratings, theirs
from practice.models import Attempt, Scenario, ScenarioSet, SetItem
from practice.sets import (
    GENERATED,
    SKILLS,
    action_scenario,
    generated_scenario,
    house_playbook,
    library_scenarios,
    own_decisions,
    record,
    skill_ratings,
)

PLANNED = 24
GRADED = ("exact", "reference", "rule")
NEARBY = 40  # unseen spots of a skill looked at for each pick
OWN_SPOTS = 6  # spots from the user's own decisions that a rule settles, made ready when a test starts
# A skill's range in the test this narrow or narrower is narrow enough to trust (practice.aptitude.report).
TRUSTED_WIDTH = 0.5
STRONG, WEAK = 0.75, 0.5  # accuracy a range must clear, at its low end, to be a strength; stay under, at its high end
# Where a skill's spots come from, besides the generated pool and the library: the user's own spots, from their
# decisions, their matches and their opponents' seats.
OWN_SOURCES = ("own_hand", "match", "their_seat")


class TestError(ValueError):
    """Something the test can't do now, such as answering a spot it isn't asking."""


@transaction.atomic
def start(user, day, rng=None):
    """A new test; its spots are chosen as it goes."""
    rng = rng or random.Random()
    _prepare_own(user, rng)
    library_scenarios()
    return ScenarioSet.objects.create(user=user, kind="test", day=day, planned=PLANNED)


def _prepare_own(user, rng):
    """Saves a few of the user's own decisions that a rule settles clearly, and a few of their opponents' ranges, so
    the test can ask them."""
    rules = house_playbook().rules
    made = 0
    for score, hand, data, context in own_decisions(user, rng):
        if made >= OWN_SPOTS:
            break
        if score >= 3:  # a clear rule applied (practice.sets.interest)
            action_scenario(user, hand, data, context, rules)
            made += 1
    theirs.spots(user, rng, actions=0, reads=OWN_SPOTS // 2)


def answered(test):
    return Attempt.objects.filter(set=test).count()


def open_item(test):
    """The spot the test is asking now, chosen and not yet answered; None if there is none."""
    done = Attempt.objects.filter(set=test).values("scenario_id")
    return test.items.exclude(scenario_id__in=done).select_related("scenario").first()


@transaction.atomic
def next_spot(test, rng=None):
    """The spot the test asks next: the open one, or a new one chosen now; None once the test is over."""
    if test.finished:
        return None
    item = open_item(test)
    if item:
        return item
    if answered(test) >= test.planned:
        return None
    rng = rng or random.Random()
    for skill in skill_order(test, rng):
        scenario = pick(test, skill, rng)
        if scenario:
            return SetItem.objects.create(set=test, scenario=scenario, position=test.items.count())
    return None  # nothing left to ask anywhere


def skill_order(test, rng):
    """The skills to try next, best first: the unprobed ones, then by the width of their range in the test."""
    asked = [item.scenario.skills[0] for item in test.items.select_related("scenario") if item.scenario.skills]
    unprobed = [skill for skill in SKILLS if skill not in asked]
    rng.shuffle(unprobed)
    shares = test_shares(test)
    rest = sorted(
        (skill for skill in SKILLS if skill in asked),
        key=lambda skill: (-_width(shares.get(skill)), asked.count(skill)),
    )
    return [*unprobed, *rest]


def _width(share):
    if not share or share["ci_low"] is None:
        return 1.0
    return (share["ci_high"] - share["ci_low"]) / 100


def test_shares(test):
    """Each skill's weighted share of good answers in the test, with its 95% Wilson range."""
    rows = {}
    for attempt in Attempt.objects.filter(set=test).select_related("scenario"):
        for skill in attempt.scenario.skills:
            row = rows.setdefault(skill, {"spots": 0, "good": 0.0, "total": 0.0})
            row["spots"] += 1
            if attempt.score is not None and attempt.weight:
                row["good"] += attempt.weight * attempt.score
                row["total"] += attempt.weight
    shares = {}
    for skill, row in rows.items():
        share = proportion(row["good"], row["total"])
        shares[skill] = {**share, "did": round(row["good"], 1), "could": round(row["total"], 1), "spots": row["spots"]}
    return shares


def candidates(user, skill):
    """The graded spots of a skill the user may be asked: generated, the library, and their own."""
    graded = Scenario.objects.filter(grading__in=GRADED)
    pools = [graded.filter(source="library"), graded.filter(source__in=OWN_SOURCES, owner=user)]
    if skill in GENERATED:
        pools.append(graded.filter(source="generated", topic__in=GENERATED[skill][1]))
    return [scenario for pool in pools for scenario in pool if skill in scenario.skills]


def pick(test, skill, rng):
    """A spot of `skill` for the test: one the user hasn't seen, its difficulty nearest their rating."""
    user = test.user
    seen = set(Attempt.objects.filter(user=user).values_list("scenario_id", flat=True))
    seen |= set(test.items.values_list("scenario_id", flat=True))
    fresh = [scenario for scenario in candidates(user, skill) if scenario.pk not in seen]
    if not fresh and skill in GENERATED:
        fresh = [generated_scenario(skill, rng)]
    if not fresh:
        return None
    rating = skill_ratings(user).get(skill, {}).get("rating", ratings.START)
    nearby = rng.sample(fresh, min(NEARBY, len(fresh)))
    return min(nearby, key=lambda scenario: abs(_difficulty(scenario) - rating))


def _difficulty(scenario):
    return scenario.difficulty if scenario.difficulty is not None else ratings.first_difficulty(scenario.tier)


@transaction.atomic
def answer(test, scenario, data, today):
    """Records an answer to the spot the test is asking, and ends the test after its last one."""
    item = open_item(test)
    if test.finished or item is None or item.scenario_id != scenario.pk:
        raise TestError("That isn't the spot the test is asking.")
    attempt = record(test.user, scenario, test, data, today)
    test.refresh_from_db()
    if test.finished:
        finish(test)
    return attempt


def finish(test):
    """Ends the test, keeping the ratings as they stand now for its report."""
    test.finished = test.finished or timezone.now()
    test.ratings = skill_ratings(test.user, test.finished)
    test.save(update_fields=["finished", "ratings"])


@transaction.atomic
def give_up(test):
    """Ends a test early: the report covers the spots answered."""
    if not test.finished:
        finish(test)


# The report ------------------------------------------------------------------------------------------------------


def report(test):
    """Everything the report shows, once the test is over."""
    shares = test_shares(test)
    skills = []
    for skill, label in SKILLS.items():
        share = shares.get(skill)
        rating = test.ratings.get(skill)
        skills.append(
            {
                "skill": skill,
                "label": label,
                "spots": share["spots"] if share else 0,
                **(_stat(share) if share else proportion(0, 0)),
                "rating": rating,
                "rating_shown": bool(rating and rating["deviation"] <= ratings.SHOWN_DEVIATION),
                "words": words(label, share),
            }
        )
    attempts = {attempt.scenario_id: attempt for attempt in Attempt.objects.filter(set=test).select_related("scenario")}
    spots = [
        {"position": item.position, "scenario": item.scenario, "attempt": attempts.get(item.scenario_id)}
        for item in test.items.select_related("scenario")
        if item.scenario_id in attempts
    ]
    return {
        "id": test.pk,
        "planned": test.planned,
        "answered": len(spots),
        "started": test.created,
        "finished": test.finished,
        "skills": skills,
        "spots": spots,
        "next": practise_next(skills),
        "minutes": _minutes(attempts.values()),
    }


def _stat(share):
    return {key: share[key] for key in ("did", "could", "pct", "ci_low", "ci_high")}


def words(label, share):
    """A skill's result in plain words, with the sample behind it."""
    if not share or not share["could"]:
        return f"{label}: not asked in this test."
    spots = share["spots"]
    counted = f"{share['did']:g} of {share['could']:g} good"
    if share["pct"] is None:
        return f"{label}: {counted}."
    ranged = f"{counted}, {share['pct']:.0f}% ({share['ci_low']:.0f}–{share['ci_high']:.0f}%)"
    if share["ci_low"] >= STRONG * 100:
        return f"{label}: a strength. {ranged}."
    if share["ci_high"] <= WEAK * 100:
        return f"{label}: a gap. {ranged}."
    if _width(share) > TRUSTED_WIDTH:
        return f"{label}: {ranged}. {spots} {'spot' if spots == 1 else 'spots'}: too few to be sure."
    return f"{label}: in between. {ranged}."


def practise_next(skills):
    """What to practise next: the weakest skill whose range is narrow enough to trust. With none narrow enough, the
    weakest tested, unless it looks like a strength; else nothing yet."""
    tested = [skill for skill in skills if skill["pct"] is not None]
    trusted = [skill for skill in tested if skill["ci_high"] - skill["ci_low"] <= TRUSTED_WIDTH * 100]
    if trusted:
        weakest = min(trusted, key=lambda skill: skill["pct"])
    else:
        weakest = min(tested, key=lambda skill: skill["pct"], default=None)
        if weakest is None or weakest["pct"] >= STRONG * 100:
            return None
    return {
        "skill": weakest["skill"],
        "label": weakest["label"],
        "trusted": bool(trusted),
        "generated": weakest["skill"] in GENERATED,
    }


def _minutes(attempts):
    taken = [attempt.time_taken for attempt in attempts if attempt.time_taken]
    return round(sum(taken) / 60, 1) if taken else None
