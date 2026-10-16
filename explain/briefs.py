"""What a model is told: the brief (pokerland-llm-reports.md, 5.2).

A brief is fixed instructions, then the subject as JSON: a hand, a practice attempt, a coach's line, a match's
debrief, an aptitude test or a session. It is built only from what the server already works out (the decision
panel's numbers, the playbook's verdicts, the preflop checks, all-in equity, the player's notes), and holds only what
the player could see: positions instead of screen names, no hidden cards, no answers before they're due.

Every provider gets the same brief, except that DeepSeek, whose JSON mode doesn't enforce a schema, also gets the
schema and an example answer in its instructions. The brief's hash covers all of it, so the answer to a brief can be
checked against the same brief rebuilt (explain.checks): if the subject changed while the model was writing, the
hashes differ.

Each kind of subject (explain.kinds) has a loader (the user's own, or 404), a readiness test (raising NotYet with why
it isn't time) and a builder. The builder returns the brief's `input`; its decisions, each with the verdict the answer
must keep and where it was, which the saved explanation keeps beside the model's words; and the links "Practise it"
may use.
"""

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from django.db.models import Max
from django.utils import timezone

from explain.schema import EXAMPLE, SCHEMA, SCHEMA_VERSION
from hands.models import Hand

INSTRUCTIONS = Path(__file__).parent / "instructions"
# A session ends after half an hour without a hand (F1), and explanations of real play wait for that.
SESSION_GAP = datetime.timedelta(minutes=30)


class NotYet(Exception):
    """The subject can't be explained yet; the message says why and when."""


@dataclass
class Brief:
    kind: str
    subject_id: int
    provider: str
    prompt_version: str
    instructions: str
    input: str
    schema: dict = field(default_factory=lambda: SCHEMA)
    decisions: dict = field(default_factory=dict)  # by ref, in order: verdict, step, street, move, rule number
    links: list = field(default_factory=list)  # what "Practise it" may point to

    @property
    def hash(self):
        """A digest of everything the model is told."""
        told = {
            "prompt_version": self.prompt_version,
            "instructions": self.instructions,
            "input": self.input,
            "schema": self.schema,
        }
        return hashlib.sha256(json.dumps(told, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def instructions(kind, provider):
    """The fixed instructions for a kind of subject, with DeepSeek's schema and example."""
    text = read("common") + "\n" + read(kind)
    if provider == "deepseek":
        mode = read("json_mode")
        mode = mode.replace("{schema}", as_json(SCHEMA)).replace("{example}", as_json(EXAMPLE))
        text += "\n" + mode
    return text


def followup_instructions(kind):
    """The instructions for a question about an explanation: the explanation's own, then how to answer. Answers
    are plain text, so no provider gets the JSON ones."""
    return read("common") + "\n" + read(kind) + "\n" + read("followup")


def read(name):
    return (INSTRUCTIONS / f"{name}.txt").read_text()


def as_json(value):
    return json.dumps(value, ensure_ascii=False)


def playing_now(user, now=None):
    """Whether the user is in a session: a hand of theirs started in the last half hour. Hands dated in the future
    are a clock's mistake, not play, and don't count."""
    now = now or timezone.now()
    latest = Hand.objects.filter(user=user, played_at__lte=now).aggregate(latest=Max("played_at"))["latest"]
    return latest is not None and latest > now - SESSION_GAP


def require_session_over(user, now=None):
    if playing_now(user, now):
        raise NotYet("Explanations open 30 minutes after your last hand, so they're never used during a session.")


def build(kind, subject, provider):
    """The brief for a subject of a kind, for a provider."""
    from explain.kinds import KINDS  # the kinds import the builders, which import this module

    spec = KINDS[kind]
    built = spec.build(subject)
    return Brief(
        kind=kind,
        subject_id=subject.pk,
        provider=provider,
        prompt_version=f"{kind}-{spec.version}.{SCHEMA_VERSION}",
        instructions=instructions(kind, provider),
        input=as_json(built["input"]),
        decisions=built["decisions"],
        links=built["links"],
    )
