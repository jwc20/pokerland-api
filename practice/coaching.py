"""Playbooks a coach writes (pokerland-practice-mode-additional.md, 7 and CM-4): a copy of a house preset, or of
one of their own, edited card by card and saved as a new version; assigned to a class (leagues); and played by its
members in coached matches. A version's cards are kept as they were, so a match played under one reads the same.

A coach sees, for each member who chose to share their progress: their stage in each of the playbook's rule families
(the handover), how often their own hands kept each of its rules (by the book), and their practice accuracy by skill.
Never their hands: only those totals (feature ideas, section 7.6).
"""

import secrets

from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from leagues.models import Assignment, Membership
from practice import book, sets
from practice.models import Playbook, RuleProgress
from practice.playbook import FAMILIES, LIMITS, clean_rules


def latest(playbook):
    """A playbook's latest version."""
    return Playbook.objects.filter(owner=playbook.owner, key=playbook.key).order_by("-version").first()


def assigned(user):
    """The playbooks assigned to the classes the user is in, as their latest versions."""
    leagues = Membership.objects.filter(user=user).values("league_id")
    found = Assignment.objects.filter(league__in=leagues, kind="playbook", withdrawn=False, playbook__archived=False)
    return Playbook.objects.filter(pk__in=found.values("playbook_id"))


def visible(user):
    """The playbooks the user can play by and read: the house presets, their own and their classes', each as its
    latest version; their own archived ones are left out."""
    sets.house_playbook()
    rows = Playbook.objects.filter(Q(owner=None) | Q(owner=user, archived=False) | Q(pk__in=assigned(user)))
    newest = {}
    for playbook in rows.order_by("owner_id", "key", "-version"):
        newest.setdefault((playbook.owner_id, playbook.key), playbook)
    return sorted(newest.values(), key=lambda playbook: (playbook.owner_id is not None, playbook.name.lower()))


def can_read(user, playbook):
    """Whether the user may read a playbook version and play by it: a house one, their own, or their class's."""
    if playbook.owner_id in (None, user.pk):
        return True
    return Playbook.objects.filter(pk__in=assigned(user), owner=playbook.owner, key=playbook.key).exists()


def classes_of(playbook):
    """The classes a playbook is assigned to now, by name."""
    found = Assignment.objects.filter(
        kind="playbook", withdrawn=False, playbook__owner=playbook.owner, playbook__key=playbook.key
    ).select_related("league")
    return sorted({assignment.league.name for assignment in found})


@transaction.atomic
def copy(user, source, name):
    """A new playbook of the user's own, version 1, with `source`'s cards."""
    key = f"{slugify(name)[:48] or 'playbook'}-{secrets.token_hex(3)}"
    return Playbook.objects.create(
        owner=user,
        key=key,
        name=name[: LIMITS["name"]],
        version=1,
        game=source.game,
        format=source.format,
        description=source.description,
        rules=clean_rules(source.rules),
    )


@transaction.atomic
def save_version(playbook, name, description, rules):
    """The next version of one of the user's playbooks, with these cards (checked: PlaybookError); the classes it is
    assigned to move to it."""
    newest = latest(playbook)
    if newest.pk != playbook.pk:
        raise ValueError(f"Version {newest.version} is the latest: edit that one.")
    version = Playbook.objects.create(
        owner=playbook.owner,
        key=playbook.key,
        name=name[: LIMITS["name"]],
        version=playbook.version + 1,
        game=playbook.game,
        format=playbook.format,
        description=description[: LIMITS["description"]],
        rules=clean_rules(rules),
    )
    Assignment.objects.filter(kind="playbook", playbook__owner=playbook.owner, playbook__key=playbook.key).update(
        playbook=version
    )
    return version


@transaction.atomic
def archive(playbook):
    """Puts a playbook away, every version, and withdraws it from the classes it was assigned to."""
    Playbook.objects.filter(owner=playbook.owner, key=playbook.key).update(archived=True)
    Assignment.objects.filter(kind="playbook", playbook__owner=playbook.owner, playbook__key=playbook.key).update(
        withdrawn=True
    )


def stages(user, playbook):
    """A user's stage in each of a playbook's rule families: 1 until a match moves it."""
    progress = {row.family: row for row in RuleProgress.objects.filter(user=user, playbook_key=playbook.key)}
    used = dict.fromkeys(rule["family"] for rule in playbook.rules)
    return [
        {
            "family": family,
            "label": FAMILIES.get(family, family),
            "stage": progress[family].stage if family in progress else 1,
            "recent": progress[family].recent if family in progress else [],
        }
        for family in FAMILIES
        if family in used
    ]


def progress(member, playbooks, with_book=False):
    """What a coach sees of a member who shares their progress: practice accuracy by skill, and for each of the
    class's playbooks their stage in each family and, with `with_book`, how their own hands kept each rule."""
    found = {"skills": sets.skill_scores(member), "playbooks": []}
    for playbook in playbooks:
        entry = {"playbook": playbook.pk, "name": playbook.name, "families": stages(member, playbook)}
        if with_book:
            entry["book"] = book.summarise(book.by_the_book(member, playbook.rules))
        found["playbooks"].append(entry)
    return found
