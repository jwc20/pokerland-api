"""The kinds of subject an explanation can be about, and how each is found, timed and briefed.

Each kind names the Explanation field that points at its subject, the version of its brief (raised whenever its
builder or instructions change, so old explanations say what they were written from), a loader that finds the user's
own subject or answers 404, a test that raises briefs.NotYet while it isn't time, and the builder.

When it's time (pokerland-llm-reports.md, 2): real play once the session is over; a practice spot once answered, and
a test's spots once the test is over; a coach's line once the player has acted on it; a debrief once the match is.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.shortcuts import get_object_or_404

from explain import hand_brief, practice_brief, session_brief
from explain.briefs import NotYet, require_session_over
from hands.models import Hand, Session
from practice.models import Attempt, CoachedMatch, MatchDecision, ScenarioSet


@dataclass(frozen=True)
class Kind:
    field: str
    version: int
    load: Callable
    ready: Callable
    build: Callable


def _hand(user, pk):
    return get_object_or_404(Hand, pk=pk, user=user)


def _real_play(user, subject):
    require_session_over(user)


def _attempt(user, pk):
    return get_object_or_404(Attempt.objects.select_related("scenario", "set"), pk=pk, user=user)


def _attempt_ready(user, attempt):
    if attempt.set and attempt.set.kind == "test" and attempt.set.finished is None:
        raise NotYet("A test's spots can be explained once the test is over.")


def _decision(user, pk):
    return get_object_or_404(MatchDecision.objects.select_related("match__playbook"), pk=pk, match__user=user)


def _decision_ready(user, decision):
    if decision.move is None:
        raise NotYet("The coach's line can be explained once you've made your move.")


def _debrief(user, pk):
    return get_object_or_404(CoachedMatch.objects.select_related("playbook", "table"), pk=pk, user=user)


def _debrief_ready(user, match):
    if match.finished is None:
        raise NotYet("The debrief can be explained once the match is over.")


def _test(user, pk):
    return get_object_or_404(ScenarioSet, pk=pk, user=user, kind="test")


def _test_ready(user, test):
    if test.finished is None:
        raise NotYet("The test can be explained once it's over.")


def _session(user, pk):
    return get_object_or_404(Session, pk=pk, user=user)


KINDS = {
    "hand": Kind(field="hand", version=1, load=_hand, ready=_real_play, build=hand_brief.build),
    "attempt": Kind(
        field="attempt", version=1, load=_attempt, ready=_attempt_ready, build=practice_brief.attempt_brief
    ),
    "decision": Kind(
        field="decision", version=1, load=_decision, ready=_decision_ready, build=practice_brief.decision_brief
    ),
    "debrief": Kind(
        field="debrief", version=1, load=_debrief, ready=_debrief_ready, build=practice_brief.debrief_brief
    ),
    "test": Kind(field="test", version=1, load=_test, ready=_test_ready, build=practice_brief.test_brief),
    "session": Kind(field="session", version=1, load=_session, ready=_real_play, build=session_brief.build),
}
