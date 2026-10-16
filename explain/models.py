from django.conf import settings
from django.db import models
from django.db.models import Q

from explain.catalog import PROVIDER_NAMES

# What an explanation can be about, each with the field that points at it.
SUBJECTS = {
    "hand": "A hand",
    "attempt": "A practice spot",
    "decision": "A coach's line",
    "debrief": "A match's debrief",
    "test": "An aptitude test",
    "session": "A session",
}


def _about(kind):
    """An explanation of `kind` points at its subject and nothing else; a session's may lose its row (rebuilt)."""
    others = Q(**{f"{field}__isnull": True for field in SUBJECTS if field != kind})
    if kind == "session":
        return Q(kind=kind) & others
    return Q(kind=kind) & others & Q(**{f"{kind}__isnull": False})


class Explanation(models.Model):
    """What a model wrote about one of the user's hands, spots, matches, tests or sessions (pokerland-llm-reports.md).

    The player's browser called the model with their own key, which never reaches Pokerland: nothing here holds a
    key, a hash of one, or any part of one. The content passed explain.checks before it was saved: the shape, the
    lengths, and every verdict the brief gave. It goes when what it explains goes, except a session's, which keeps
    the period it covered because rebuilding sessions can replace their rows.
    """

    PROVIDERS = PROVIDER_NAMES

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="explanations")
    kind = models.CharField(max_length=16, choices=SUBJECTS)
    hand = models.ForeignKey("hands.Hand", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    attempt = models.ForeignKey("practice.Attempt", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    decision = models.ForeignKey(
        "practice.MatchDecision", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    debrief = models.ForeignKey(
        "practice.CoachedMatch", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    test = models.ForeignKey("practice.ScenarioSet", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    session = models.ForeignKey("hands.Session", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    period_start = models.DateTimeField(null=True, blank=True)  # a session's first hand
    period_end = models.DateTimeField(null=True, blank=True)  # and its last
    prompt_version = models.CharField(max_length=24)  # explain.briefs: which builder, instructions and schema
    brief_hash = models.CharField(max_length=64)  # what the model was told, to tell when the subject has changed
    provider = models.CharField(max_length=16, choices=PROVIDERS)
    model = models.CharField(max_length=64)  # as the provider reported it
    effort = models.CharField(max_length=8, blank=True)
    content = models.JSONField()  # explain.schema's shape, checked
    usage = models.JSONField(default=dict, blank=True)  # tokens: input (read afresh), cached_input, cache_write, output
    cost = models.FloatField(null=True, blank=True)  # about what it cost, in US dollars, at the prices of the day
    request_id = models.CharField(max_length=128, blank=True)  # the provider's, for its support
    useful = models.BooleanField(null=True, blank=True)  # the player's rating; null until they rate it
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=_about("hand")
                | _about("attempt")
                | _about("decision")
                | _about("debrief")
                | _about("test")
                | _about("session"),
                name="explanation_about_its_subject",
            )
        ]
        indexes = [models.Index(fields=("user", "-created"), name="explanation_created")]
        ordering = ("-created", "-id")

    def __str__(self):
        return f"{self.kind} explanation #{self.pk} for {self.user}"


class ExplanationTurn(models.Model):
    """A question the player asked about an explanation, and the answer, written the same way: by a model their
    browser called with their own key."""

    explanation = models.ForeignKey(Explanation, on_delete=models.CASCADE, related_name="turns")
    question = models.TextField()
    answer = models.TextField()
    provider = models.CharField(max_length=16, choices=Explanation.PROVIDERS)
    model = models.CharField(max_length=64)
    usage = models.JSONField(default=dict, blank=True)
    cost = models.FloatField(null=True, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created", "id")

    def __str__(self):
        return f"Question #{self.pk} on {self.explanation}"
