"""Classes (feature ideas, G4; pokerland-practice-mode.md, 4.3; the coached-match doc, 7): a league with coaches and
members, who join with its invite code.

- **A coach** assigns playbooks of their own (practice.coaching) and hands to study, and sees the progress of the
  members who chose to share it: totals only, never their hands (feature ideas, section 7.6).
- **Anyone in the class** can share one of their hands with it: an E2 share, shown anonymized, players by position.
  Its sharer, or a coach, can withdraw it, and so can revoking the share; either way it leaves the class's list and
  its members' future sets (practice.sets.shared_set).
- **The owner** made the class and stays a coach in it. They alone make other members coaches, and can't leave it.
"""

import secrets

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from hands.models import HandShare
from hands.shares import new_slug
from leagues.models import Assignment, League, Membership

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, so a code read aloud survives
CODE_LENGTH = 8


class ClassError(Exception):
    """Something a class doesn't allow, said for the user."""


def new_code():
    """An invite code no class has: eight letters and digits, easy to read out."""
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if not League.objects.filter(invite_code=code).exists():
            return code


def normal_code(code):
    """An invite code as typed, made comparable: no spaces or dashes, upper case."""
    return "".join(code.split()).replace("-", "").upper()


def mine(user):
    """The classes the user is in, with their own role and the number of members and active assignments."""
    return (
        League.objects.filter(memberships__user=user)
        .annotate(
            member_count=Count("memberships", distinct=True),
            assignment_count=Count(
                "assignments",
                filter=Q(assignments__withdrawn=False) & ~Q(assignments__share__revoked=True),
                distinct=True,
            ),
        )
        .distinct()
    )


def membership(user, league):
    """The user's membership of a class, or None."""
    return Membership.objects.filter(user=user, league=league).first()


@transaction.atomic
def create(user, name):
    """A new class, with the user its owner and first coach."""
    league = League.objects.create(name=name.strip(), owner=user, invite_code=new_code())
    Membership.objects.create(league=league, user=user, role="coach")
    return league


def join(user, code):
    """Joins the class with this invite code, as a member; joining one you're in already changes nothing."""
    league = League.objects.filter(invite_code=normal_code(code)).first()
    if not league:
        raise ClassError("No class has that invite code.")
    try:
        with transaction.atomic():
            Membership.objects.get_or_create(league=league, user=user)
    except IntegrityError:
        pass  # joined at the same moment by another request
    return league


def new_invite(league):
    """A fresh invite code; the old one stops working, and nobody already in the class is affected."""
    league.invite_code = new_code()
    league.save(update_fields=["invite_code"])
    return league


def leave(member):
    """The user leaves the class: their assignments go with them, and so does what they shared of their progress."""
    if member.league.owner_id == member.user_id:
        raise ClassError("You made this class, so you can't leave it.")
    with transaction.atomic():
        Assignment.objects.filter(league=member.league, by=member.user).update(withdrawn=True)
        member.delete()


def set_role(member, role):
    """A member made a coach, or a coach a member; never the owner, who stays a coach."""
    if member.league.owner_id == member.user_id and role != "coach":
        raise ClassError("The class's owner stays a coach.")
    member.role = role
    member.save(update_fields=["role"])
    return member


def active(league):
    """The class's assignments still before it: not withdrawn, and for a hand, a share that's still live."""
    return (
        Assignment.objects.filter(league=league, withdrawn=False)
        .exclude(kind="hand", share__revoked=True)
        .exclude(kind="playbook", playbook__archived=True)
        .select_related("by", "playbook", "share__hand")
    )


def playbooks(league):
    """The playbooks assigned to a class now, each as its latest version."""
    return [assignment.playbook for assignment in active(league).filter(kind="playbook")]


@transaction.atomic
def assign_playbook(member, playbook, note=""):
    """A coach assigns one of their own playbooks, at its latest version; assigning one already assigned updates the
    note."""
    from practice import coaching

    if member.role != "coach":
        raise ClassError("Only a coach assigns playbooks.")
    if playbook.owner_id != member.user_id or playbook.archived:
        raise ClassError("You can assign only playbooks of your own that you haven't put away.")
    playbook = coaching.latest(playbook)
    existing = Assignment.objects.filter(
        league=member.league,
        kind="playbook",
        withdrawn=False,
        playbook__owner=playbook.owner,
        playbook__key=playbook.key,
    ).first()
    if existing:
        existing.playbook, existing.note = playbook, note
        existing.save(update_fields=["playbook", "note"])
        return existing
    return Assignment.objects.create(
        league=member.league, by=member.user, kind="playbook", playbook=playbook, note=note
    )


@transaction.atomic
def share_hand(member, hand, note=""):
    """Anyone in a class shares one of their hands with it, by their live E2 share of it, made anonymized if they have
    none. The class always sees it anonymized, whatever the share's public page does. Revoking the share takes it off
    the class. Sharing one already shared updates the note."""
    if hand.user_id != member.user_id:
        raise ClassError("You can share only your own hands.")
    share = HandShare.objects.filter(user=member.user, hand=hand, revoked=False).first()
    if not share:
        share = HandShare.objects.create(user=member.user, hand=hand, slug=new_slug(), anonymize=True)
    existing = Assignment.objects.filter(league=member.league, kind="hand", withdrawn=False, share=share).first()
    if existing:
        existing.note = note
        existing.save(update_fields=["note"])
        return existing
    return Assignment.objects.create(league=member.league, by=member.user, kind="hand", share=share, note=note)


def withdraw(member, assignment):
    """Takes an assignment off the class: by whoever put it there, or by a coach."""
    if assignment.by_id != member.user_id and member.role != "coach":
        raise ClassError("Only whoever shared it, or a coach, can withdraw it.")
    assignment.withdrawn = True
    assignment.save(update_fields=["withdrawn"])


def shared_hands(user):
    """The hands shared with the user's classes and still live, other than their own: (assignment, share) pairs, the
    newest first. A hand shared with two of their classes comes once."""
    leagues = Membership.objects.filter(user=user).values("league_id")
    found = (
        Assignment.objects.filter(league__in=leagues, kind="hand", withdrawn=False, share__revoked=False)
        .exclude(share__user=user)
        .select_related("league", "by", "share__hand")
        .order_by("-created", "-id")
    )
    seen = set()
    pairs = []
    for assignment in found:
        if assignment.share.hand_id not in seen:
            seen.add(assignment.share.hand_id)
            pairs.append((assignment, assignment.share))
    return pairs


def can_practise(user, hand_id):
    """Whether a hand is shared, live, with one of the user's classes, so its spots are the user's to answer."""
    return any(share.hand_id == hand_id for _, share in shared_hands(user))


def sharing(league):
    """The members of a class who share their progress with its coaches."""
    return Membership.objects.filter(league=league, role="member", shares_progress=True).select_related("user")


def progress(league):
    """What a class's coaches see of every member who shares their progress: practice accuracy and their stage in
    each assigned playbook's families (practice.coaching). By the book reads up to a thousand hands a member, so it
    comes one member at a time (member_progress)."""
    from practice import coaching

    members = list(sharing(league))
    found = coaching.progress_of([member.user for member in members], playbooks(league))
    return [{"member": member.pk, "name": member.user.username, **found[member.user_id]} for member in members]


def member_progress(member):
    """One sharing member's progress, with how their own hands kept each assigned playbook's rules."""
    from practice import coaching

    found = coaching.progress(member.user, playbooks(member.league), with_book=True)
    return {"member": member.pk, "name": member.user.username, **found}
