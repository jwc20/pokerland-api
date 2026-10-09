from django.conf import settings
from django.db import models


class League(models.Model):
    """A group that studies together (G1 and G4 of the feature ideas). For now every league is a class: one or more
    coaches and their members, who join with the invite code. A coach writes and assigns playbooks (practice.Playbook)
    and hands to study; a member can share a hand with the class; and a coach sees the practice progress of the
    members who choose to share it. Leaderboards and events (G1, G2) come later, on the same rows.
    """

    KINDS = {"class": "A class"}

    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, choices=KINDS, default="class")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leagues_owned")
    invite_code = models.CharField(max_length=16, unique=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class Membership(models.Model):
    """A user in a league, as a coach or a member. Members opt in to showing the coaches their practice progress;
    nothing is shown until they do, and never their hands themselves (feature ideas, section 7.6)."""

    ROLES = {"coach": "Coach", "member": "Member"}

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=8, choices=ROLES, default="member")
    shares_progress = models.BooleanField(default=False)
    joined = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("league", "user"), name="one_membership_per_league")]
        ordering = ("joined", "id")

    def __str__(self):
        return f"{self.user} in {self.league} as {self.role}"


class Assignment(models.Model):
    """Something put before a class: a playbook a coach assigns, or a hand shared with it, anonymized, by a coach (an
    assignment) or a member. Withdrawn, it leaves the class's list and its future sets; a revoked share does too."""

    KINDS = {"playbook": "A playbook", "hand": "A hand"}

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="assignments")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=8, choices=KINDS)
    # A playbook's assignment follows its latest version: saving a new one moves the assignment to it.
    playbook = models.ForeignKey("practice.Playbook", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    share = models.ForeignKey("hands.HandShare", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    note = models.CharField(max_length=500, blank=True)
    withdrawn = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created", "-id")

    def __str__(self):
        return f"{self.get_kind_display()} for {self.league}"
