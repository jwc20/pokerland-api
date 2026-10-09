"""Results worked out from a user's hands, kept so the next request for the same thing needn't work them out again.

Stats, leaks, the reports and by the book read thousands of a user's hands, but their answers change only when what
they read does: the user's hands (with what hands.store writes beside them: players, bets, sessions, opponents and
tournaments), their leak presets and reviews, and their saved spots. So an answer is kept in the database, where every
Lambda instance finds it (memory isn't shared between them), with the user's data version (DataVersion) when it was
worked out. Whatever changes that data calls `changed`, which moves the version on, and an answer kept under an older
one is worked out again. Notes don't count: no kept answer reads them.

- **Exact, even mid-upload.** The version is read before the work starts. An answer worked out while an upload
  commits is kept under the old version, so it is never served after the upload.
- **A deploy starts afresh.** Each answer is kept with a fingerprint of the code that works answers out (`CODE`), so
  when that code changes nothing old is served, and nobody needs to clear anything.
- **Answers that look back from now,** such as by the book's hands "at least a day old", put what they depend on in
  their parameters.

Writes that call `changed`: hands.store (uploads and reparses), hands.sessions.rebuild, and the receivers in
hands.signals (a hand saved on its own, leak presets and reviews, saved spots, deleted streams). Code that changes
that data in any other way, such as deleting some hands, must call it too; so must a kept answer that starts reading
something new.

Answers are kept as JSON text, not a JSON column: PostgreSQL's jsonb (and SQLite's) reorder an object's keys, and a
kept answer must come back exactly as it was worked out.
"""

import hashlib
import json
from pathlib import Path

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F, PositiveBigIntegerField, Subquery, Value
from django.db.models.functions import Coalesce

from hands.models import DataVersion, KeptResult

ROOT = Path(__file__).resolve().parent.parent
# The code whose answers are kept: the apps that work them out, and the parser whose output they read.
SOURCES = ("hands", "practice", "tracker/parsing")


def _fingerprint():
    """A short digest of the source of SOURCES, tests and migrations aside."""
    digest = hashlib.sha256()
    for folder in SOURCES:
        for path in sorted((ROOT / folder).glob("*.py")):
            if not path.name.startswith("tests"):
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


CODE = _fingerprint()


def key_of(name, params):
    """A kept answer's key: its name, and a digest of the parameters it was asked with, in any order."""
    if hasattr(params, "lists"):  # a QueryDict: each parameter with every value it was given
        params = {name: sorted(values) for name, values in params.lists()}
    text = json.dumps(params, sort_keys=True, cls=DjangoJSONEncoder)
    return f"{name}:{hashlib.sha256(text.encode()).hexdigest()[:32]}"


def version_of(user_id):
    return DataVersion.objects.filter(user_id=user_id).values_list("version", flat=True).first() or 0


def changed(user_id):
    """The user's data has changed: every answer kept for them is out of date.

    Call it in the transaction that changes the data, so the two commit together.
    """
    DataVersion.objects.get_or_create(user_id=user_id)
    DataVersion.objects.filter(user_id=user_id).update(version=F("version") + 1)
    # The old answers no longer hold, so they needn't take up room. Deleted once the change commits, so an upload's
    # transaction doesn't hold their rows; one kept meanwhile by a request still running is caught by its version.
    transaction.on_commit(lambda: KeptResult.objects.filter(user_id=user_id).delete())


def lookup(user_id, keys):
    """The answers kept under `keys` that still hold: {key: value}. One query, the version read in it."""
    current = Subquery(DataVersion.objects.filter(user_id=user_id).values("version")[:1])
    version = Coalesce(current, Value(0), output_field=PositiveBigIntegerField())
    rows = KeptResult.objects.filter(user_id=user_id, key__in=keys, code=CODE, version=version)
    return {key: json.loads(text) for key, text in rows.values_list("key", "value")}


def keep(user_id, version, answers):
    """Keeps `answers` ({key: value}) as worked out at `version`, in place of any kept before under their keys."""
    KeptResult.objects.bulk_create(
        [
            KeptResult(user_id=user_id, key=key, version=version, code=CODE, value=as_text(value))
            for key, value in answers.items()
        ],
        update_conflicts=True,
        unique_fields=("user", "key"),
        update_fields=("version", "code", "value", "made"),
    )


def as_text(value):
    return json.dumps(value, cls=DjangoJSONEncoder)


def plain(value):
    """`value` as a kept answer comes back, so an answer served fresh and one served kept are alike to the byte."""
    return json.loads(as_text(value))


def remembered(user_id, name, params, work):
    """`work()`'s answer for `name` asked with `params`: the kept one if it still holds, else worked out and kept."""
    key = key_of(name, params)
    found = lookup(user_id, [key])
    if key in found:
        return found[key]
    version = version_of(user_id)  # before the work, so an answer that misses a change is kept as older than it
    value = plain(work())
    keep(user_id, version, {key: value})
    return value
