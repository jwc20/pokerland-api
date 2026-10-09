"""Ratings, the aptitude model's version 2 (pokerland-practice-mode.md, 6): a Glicko rating for each user and skill,
and one for each spot's difficulty, learned from everyone's attempts at it.

Every graded answer is a game between a user's skill and a spot. A good answer wins it for the user, a poor one for
the spot, and partial credit (an acceptable answer, a range's overlap) is a result in between. Glicko-1 [Glickman
1999] updates both after each answer, one game at a time. A rating's deviation is its uncertainty: it starts at 350,
narrows with each answer and widens again with time away, and rating ± 1.96 deviations is shown as its 95% range.

Two choices of ours, beside the method itself:

- **A rule of thumb counts half** here as in the accuracy (practice.sets.WEIGHTS): its game moves the rating, and
  narrows the range, by half as much. A reflection isn't a game at all.
- **A spot's first difficulty** comes from its tier, 1 to 3: 1350, 1500 or 1650, with the full deviation, so the first
  answers to it say more than the guess does.

Django-free; practice.aptitude applies it to the models.
"""

import math

Q = math.log(10) / 400
START, START_DEVIATION = 1500.0, 350.0
MIN_DEVIATION = 30.0
# How fast a deviation widens with time away: from 50 back to 350 in about a hundred days.
WIDENING = math.sqrt((START_DEVIATION**2 - 50**2) / 100)
TIER_DIFFICULTY = {1: 1350.0, 2: 1500.0, 3: 1650.0}
# A rating is shown once its range is this narrow; until then, the accuracy alone (version 1).
SHOWN_DEVIATION = 150


def g(deviation):
    """How much a result against a rating this uncertain says: 1 for a certain one, less the wider it is."""
    return 1 / math.sqrt(1 + 3 * Q**2 * deviation**2 / math.pi**2)


def expected(rating, other, other_deviation):
    """The result a rating expects against another: from 0 to 1."""
    return 1 / (1 + 10 ** (-g(other_deviation) * (rating - other) / 400))


def update(rating, deviation, other, other_deviation, score, weight=1.0):
    """A rating and its deviation after one result against `other`: `score` from 0 (a loss) to 1 (a win), counting
    at `weight`."""
    gj = g(other_deviation)
    e = expected(rating, other, other_deviation)
    variance = 1 / (1 / deviation**2 + Q**2 * gj**2 * e * (1 - e))
    moved = rating + Q * variance * gj * (score - e)
    narrowed = deviation**2 - weight * (deviation**2 - variance)
    return rating + weight * (moved - rating), max(MIN_DEVIATION, math.sqrt(narrowed))


def widened(deviation, days):
    """A deviation after `days` without a result: it widens again, up to where it started."""
    return min(START_DEVIATION, math.sqrt(deviation**2 + WIDENING**2 * max(0.0, days)))


def interval(rating, deviation):
    """A rating's 95% range."""
    return rating - 1.96 * deviation, rating + 1.96 * deviation


def first_difficulty(tier):
    """A spot's difficulty before anyone has answered it, from its tier."""
    return TIER_DIFFICULTY.get(tier, START)
