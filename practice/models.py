from django.conf import settings
from django.db import models

from practice.playbook import FAMILIES


class Scenario(models.Model):
    """A spot to practise: a table to draw, a question about it, and its answer, held back until an attempt.

    `spec` is what the client draws and asks (practice.serializers.ScenarioSpecSerializer); `answer` is how the
    question is graded. Generated spots belong to no one and are shared, so what they teach about a spot's
    difficulty comes from everyone's attempts. A spot from a user's hand is theirs and goes with the hand.
    """

    SOURCES = {
        "own_hand": "One of your hands",
        "generated": "Generated",
        "match": "A coached match",
    }
    GRADINGS = {
        "exact": "Exact",
        "reference": "Reference range",
        "rule": "Rule of thumb",
        "reflection": "Reflection",
    }

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="scenarios"
    )
    source = models.CharField(max_length=16, choices=SOURCES)
    hand = models.ForeignKey("hands.Hand", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    step = models.PositiveIntegerField(null=True, blank=True)  # the event the decision is, in the hand's events
    topic = models.CharField(max_length=32)  # what it asks: "action", "equity_needed", "mdf", ...
    origin = models.JSONField(default=dict, blank=True)  # where a generated or match spot came from
    spec = models.JSONField()
    answer = models.JSONField()
    grading = models.CharField(max_length=16, choices=GRADINGS)
    skills = models.JSONField(default=list)
    tier = models.PositiveSmallIntegerField(default=1)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "hand", "step", "topic"),
                condition=models.Q(hand__isnull=False),
                name="one_scenario_per_decision_and_topic",
            )
        ]
        indexes = [models.Index(fields=("source", "topic"), name="scenario_kind")]

    def __str__(self):
        return f"{self.get_source_display()}: {self.topic} #{self.pk}"


class ScenarioSet(models.Model):
    """A short run of spots, in order: today's set, a mode's set, or one built from a match's misses."""

    KINDS = {"daily": "Today's set", "my_hands": "My hands", "generated": "Generated", "match": "From a match"}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_sets")
    kind = models.CharField(max_length=16, choices=KINDS)
    day = models.DateField()  # the user's day it was made for
    skill = models.CharField(max_length=32, blank=True)  # a generated set's skill
    scenarios = models.ManyToManyField(Scenario, through="SetItem", related_name="sets")
    created = models.DateTimeField(auto_now_add=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "day"), condition=models.Q(kind="daily"), name="one_daily_set_per_day"
            )
        ]
        ordering = ("-created",)

    def __str__(self):
        return f"{self.get_kind_display()} for {self.user} on {self.day}"


class SetItem(models.Model):
    set = models.ForeignKey(ScenarioSet, on_delete=models.CASCADE, related_name="items")
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="+")
    position = models.PositiveSmallIntegerField()
    review = models.BooleanField(default=False)  # a spot coming back from an earlier miss

    class Meta:
        constraints = [models.UniqueConstraint(fields=("set", "position"), name="one_spot_per_position")]
        ordering = ("position",)


class Attempt(models.Model):
    """An answer to a spot, and how it was graded: never by the card that came, only by the decision."""

    GRADES = {"good": "Good", "acceptable": "Acceptable", "poor": "Poor", "ungraded": "Not graded"}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="attempts")
    set = models.ForeignKey(ScenarioSet, on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts")
    choice = models.PositiveSmallIntegerField(null=True, blank=True)  # a multiple-choice answer's index
    action = models.CharField(max_length=8, blank=True)  # fold, check, call, bet or raise
    amount = models.BigIntegerField(null=True, blank=True)  # a bet or raise's chips: the total it makes, `to`
    reason = models.CharField(max_length=16, blank=True)  # from the reason picker
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)  # 1 to 5
    time_taken = models.FloatField(null=True, blank=True)  # seconds
    grade = models.CharField(max_length=12, choices=GRADES)
    score = models.FloatField(null=True, blank=True)  # 1, 0.5 or 0; none for reflection
    weight = models.FloatField(default=1)  # how much it counts toward a skill: a rule of thumb counts half
    ev_lost_bb = models.FloatField(null=True, blank=True)
    rule = models.CharField(max_length=40, blank=True)  # the playbook card it was graded by
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("user", "-created"), name="attempt_recent")]

    def __str__(self):
        return f"{self.user} on {self.scenario}: {self.grade}"


class Review(models.Model):
    """A spot that comes back, Leitner-style: a miss or an "again later" starts in box 1; each good answer moves
    it up a box and further away, until it leaves the last one."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="reviews")
    box = models.PositiveSmallIntegerField(default=1)
    due = models.DateField()
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "scenario"), name="one_review_per_spot")]
        indexes = [models.Index(fields=("user", "due"), name="review_due")]


class Playbook(models.Model):
    """A named, versioned list of rule cards (practice.playbook). A version's cards are kept as they were."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="playbooks"
    )  # none for a house preset
    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=1)
    game = models.CharField(max_length=64)
    format = models.CharField(max_length=16)
    description = models.TextField(blank=True)
    rules = models.JSONField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("owner", "key", "version"), name="one_playbook_version")]

    def __str__(self):
        return f"{self.name} v{self.version}"


class RuleProgress(models.Model):
    """How far the coach has handed one rule family over to a user: stage 1 (watch) to 4 (solo).

    `recent` keeps the last decisions in the family that a rule decided: whether each kept the playbook without
    asking the coach, newest last. It moves the stage up and down (practice.coach).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rule_progress")
    playbook_key = models.SlugField(max_length=64)  # kept across versions, so a new version keeps the stages
    family = models.CharField(max_length=24, choices=FAMILIES)
    stage = models.PositiveSmallIntegerField(default=1)
    recent = models.JSONField(default=list)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "playbook_key", "family"), name="one_progress_per_family")
        ]


class PracticeTable(models.Model):
    """A table on the server where a user plays whole hands against bots, one PracticeHand after another.

    `seats` holds each seat's name, stack between hands and, for a bot, its style and leak, which stay on the
    server until a match's debrief.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_tables")
    seats = models.JSONField()
    small_blind = models.PositiveIntegerField()
    big_blind = models.PositiveIntegerField()
    button_seat = models.PositiveSmallIntegerField()
    hands_played = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)


class PracticeHand(models.Model):
    """One hand at a practice table: the deck it is dealt from, every move so far, and what it looks like.

    The deck is shuffled when the hand starts, so the cards to come are fixed but unseen; practice.table rebuilds
    the PokerKit state from `deck` and `moves` on each request. `replay` holds the seats, events and board in the
    stored hands' format, with every player's cards: the API shows a bot's only once they are shown down.
    """

    table = models.ForeignKey(PracticeTable, on_delete=models.CASCADE, related_name="hands")
    number = models.PositiveIntegerField()
    small_blind = models.PositiveIntegerField()
    big_blind = models.PositiveIntegerField()
    button_seat = models.PositiveSmallIntegerField()
    stacks = models.JSONField()  # each seat's chips at the start, in seat order
    deck = models.CharField(max_length=104)
    moves = models.JSONField(default=list)
    replay = models.JSONField(default=dict)
    phh = models.TextField(blank=True)
    finished = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("table", "number"), name="one_hand_per_number")]
        ordering = ("number",)


class CoachedMatch(models.Model):
    """A short heads-up match against a bot with a leak, with a coach who hands over (practice.coach).

    The bot's style and leak live on the table's seat, hidden until the match is over.
    """

    OPPONENTS = {
        "mystery": "Mystery",
        "tag": "Tight-aggressive",
        "lag": "Loose-aggressive",
        "station": "Calling station",
        "rock": "Rock",
    }
    COACH = {"progress": "Follow my progress", "1": "Watch", "2": "Call it", "3": "Play, then hear it", "4": "Solo"}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches")
    table = models.OneToOneField(PracticeTable, on_delete=models.CASCADE, related_name="match")
    playbook = models.ForeignKey(Playbook, on_delete=models.PROTECT, related_name="matches")
    opponent = models.CharField(max_length=16, choices=OPPONENTS)
    coach = models.CharField(max_length=16, choices=COACH, default="progress")
    starting_bb = models.PositiveSmallIntegerField(default=40)
    hands_planned = models.PositiveSmallIntegerField(default=30)
    time_bank = models.FloatField(default=60)  # seconds left in the match's time bank
    result_bb = models.FloatField(null=True, blank=True)  # chips won, in starting big blinds
    expected_bb = models.FloatField(null=True, blank=True)  # chips expected when the money went in
    started = models.DateTimeField(auto_now_add=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started",)


class MatchDecision(models.Model):
    """One of the user's decisions in a match: what it faced, what the playbook said, and what they did."""

    match = models.ForeignKey(CoachedMatch, on_delete=models.CASCADE, related_name="decisions")
    hand = models.ForeignKey(PracticeHand, on_delete=models.CASCADE, related_name="decisions")
    step = models.PositiveIntegerField()  # the event the decision is, in the hand's events
    context = models.JSONField()
    advice = models.JSONField()
    stage = models.PositiveSmallIntegerField()
    intent = models.JSONField(null=True, blank=True)  # stage 2: what they said they would do, and why
    move = models.JSONField(null=True, blank=True)  # what they did, as practice.spots describes a move
    reason = models.CharField(max_length=16, blank=True)
    followed = models.BooleanField(null=True)  # null until they act
    asked = models.BooleanField(default=False)  # asked the coach before acting
    departure = models.CharField(max_length=16, blank=True)  # why they left the rule: read, price, stack, felt
    time_taken = models.FloatField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("hand", "step"), name="one_decision_per_step")]
        ordering = ("hand__number", "step")


class ReadNote(models.Model):
    """A line on the read card, by the coach or the user: what a showdown told them, a read on the opponent, or a
    label for their style. Revising a note replaces it and withdrawing a read keeps it: the card keeps the history.
    """

    KINDS = {"showdown": "Showdown note", "read": "Read", "label": "Label"}
    BY = {"coach": "Coach", "user": "You"}

    match = models.ForeignKey(CoachedMatch, on_delete=models.CASCADE, related_name="read_notes")
    hand_number = models.PositiveIntegerField(null=True, blank=True)
    kind = models.CharField(max_length=16, choices=KINDS)
    tag = models.CharField(max_length=32)
    evidence = models.JSONField(default=dict, blank=True)
    by = models.CharField(max_length=8, choices=BY)
    replaced_by = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    withdrawn = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created", "id")
