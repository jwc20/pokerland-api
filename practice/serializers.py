from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from hands import ranges
from hands.filters import UTC
from hands.serializers import HandEventSerializer, HandPlayerSerializer, TimeZoneField
from practice import charts, coaching, play, shared
from practice.models import Attempt, CoachedMatch, Playbook, PracticeTable, Scenario, ScenarioSet
from practice.playbook import FAMILIES, READS
from practice.reads import ONE_OFF, TAGS
from practice.sets import SKILLS, hand_data, outcome_of

ACTIONS = ["fold", "check", "call", "bet", "raise"]
SKILL_CHOICES = list(SKILLS)
VERDICTS = ["clear", "close", "your_call"]
BASES = ["exact", "rule", "adjustment", "none"]
REASONS = ["value", "bluff", "draw", "protect", "bluff_catch", "price", "trap", "give_up", "cant_say"]


class TimeZoneQuerySerializer(serializers.Serializer):
    tz = TimeZoneField(
        required=False, default=UTC, help_text='The IANA time zone the user\'s days are counted in; UTC if left out.'
    )


class TableHandSerializer(serializers.Serializer):
    """A hand up to a decision, in the stored hands' replay format: what the client's buildReplay draws."""

    game = serializers.CharField()
    currency = serializers.CharField(allow_blank=True, help_text="Empty for chips; amounts are cents otherwise.")
    small_blind = serializers.IntegerField()
    big_blind = serializers.IntegerField()
    ante = serializers.IntegerField()
    tournament_id = serializers.CharField(allow_blank=True)
    button_seat = serializers.IntegerField()
    max_seats = serializers.IntegerField(allow_null=True)
    hero = serializers.CharField(help_text="The player whose decision it is.")
    players = HandPlayerSerializer(
        many=True, help_text="In seat order, with nobody's cards but the hero's and no results."
    )
    events = HandEventSerializer(many=True, help_text="Every event before the decision.")


class LegalSerializer(serializers.Serializer):
    """The moves the decision allows. Amounts are chips, or cents with a currency."""

    to_call = serializers.IntegerField(help_text="0 when checking is free.")
    can_check = serializers.BooleanField()
    can_raise = serializers.BooleanField()
    raise_kind = serializers.ChoiceField(choices=["bet", "raise"])
    min_to = serializers.IntegerField(allow_null=True, help_text="The least a bet or raise can make your bet.")
    max_to = serializers.IntegerField(allow_null=True, help_text="All-in.")
    bet = serializers.IntegerField(help_text="Chips already in front of you on this street.")
    stack = serializers.IntegerField(help_text="Chips behind.")


class AmountsField(serializers.DictField):
    """The chips of each amount a text writes as "{a0}", "{a1}", ...: the client writes them in its unit."""

    def __init__(self, **kwargs):
        help_text = 'The chips of each amount the text writes as "{a0}", "{a1}", ...'
        super().__init__(child=serializers.IntegerField(), required=False, help_text=help_text, **kwargs)


class QuestionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["action", "choice", "range"],
        help_text="What to do, a choice of up to four, or a range of hands picked on the grid.",
    )
    prompt = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField(), required=False)
    unit = serializers.ChoiceField(choices=["percent", "ratio", "number"], required=False)
    all_in_only = serializers.BooleanField(required=False, help_text="The only raise is all-in: push or fold.")
    amounts = AmountsField()


class ScenarioSpecSerializer(serializers.Serializer):
    """What the client draws and asks; the answer stays on the server until an attempt."""

    hand = TableHandSerializer(allow_null=True, help_text="Null for a spot with no table, such as a toy game.")
    setup = serializers.CharField(required=False, help_text="A spot with no table: its setup, in words.")
    title = serializers.CharField(required=False, help_text="A library spot: the example's name.")
    credit = serializers.CharField(required=False, help_text="A library spot: the lectures it comes from.")
    labels = serializers.ChoiceField(
        choices=["names", "positions"], help_text="Seats show names in the user's own hands, positions otherwise."
    )
    revealed = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()), help_text="Cards shown with the spot, by player."
    )
    question = QuestionSerializer()
    legal = LegalSerializer(required=False)
    panel = serializers.BooleanField(help_text="Whether the decision panel may show: never when it holds the answer.")


class ScenarioSerializer(serializers.ModelSerializer):
    spec = ScenarioSpecSerializer()
    skills = serializers.ListField(child=serializers.ChoiceField(choices=SKILL_CHOICES))

    class Meta:
        model = Scenario
        fields = ("id", "source", "topic", "grading", "skills", "tier", "spec")
        read_only_fields = fields


class MoveSerializer(serializers.Serializer):
    """A move as the playbook's rules read it. Amounts are chips."""

    action = serializers.ChoiceField(choices=ACTIONS)
    all_in = serializers.BooleanField(required=False)
    amount = serializers.IntegerField(required=False, help_text="Chips put in with it.")
    amount_bb = serializers.FloatField(required=False)
    to = serializers.IntegerField(required=False, help_text="A bet or raise: the bet it makes.")
    to_bb = serializers.FloatField(required=False)
    pot_before = serializers.IntegerField(
        required=False, help_text="A bet or raise: everything in the middle before it."
    )
    size = serializers.FloatField(required=False, allow_null=True, help_text="A bet or raise: its chips ÷ pot_before.")


class AdviceSerializer(serializers.Serializer):
    """What the playbook says about a decision (practice.rules.evaluate)."""

    rule = serializers.CharField(allow_null=True, help_text="The card in play; null when no card decides it.")
    rules = serializers.ListField(child=serializers.CharField(), help_text="Every card that applied.")
    family = serializers.ChoiceField(choices=list(FAMILIES))
    action = serializers.ChoiceField(choices=ACTIONS)
    accepts = serializers.ListField(child=serializers.ChoiceField(choices=ACTIONS), help_text="Moves that keep it.")
    size = serializers.FloatField(allow_null=True, help_text="A bet's size, as a share of the pot.")
    to_bb = serializers.FloatField(
        allow_null=True, help_text="A raise before the flop: the bet it makes, in big blinds."
    )
    verdict = serializers.ChoiceField(choices=VERDICTS)
    basis = serializers.ChoiceField(choices=BASES)
    conflict = serializers.BooleanField(required=False, help_text="Two cards disagree, so it is close.")
    sizing_rule = serializers.CharField(required=False, help_text="The card a bet's size comes from.")
    outs = serializers.IntegerField(help_text="Clean outs your draws have.")
    draw_equity = serializers.FloatField(help_text="Their chance of coming, on the next card or by the river all-in.")


class RuleCardSerializer(serializers.Serializer):
    """A playbook card: the rule, why, who it is for, its exceptions and its source."""

    id = serializers.CharField()
    number = serializers.IntegerField()
    family = serializers.ChoiceField(choices=list(FAMILIES))
    kind = serializers.ChoiceField(choices=["action", "sizing"], required=False)
    rule = serializers.CharField()
    why = serializers.CharField()
    scope = serializers.CharField(help_text='"anyone", "heads_up", or the read an adjustment is for.')
    simplification = serializers.BooleanField(required=False, help_text="Training wheels, swapped out in time.")
    exceptions = serializers.CharField(required=False)
    adjustment = serializers.BooleanField(required=False)
    read = serializers.ChoiceField(choices=list(READS), required=False)
    source = serializers.ListField(child=serializers.CharField())
    when = serializers.DictField(
        child=serializers.JSONField(), required=False, help_text="The test the card runs: {condition: value}."
    )
    unless = serializers.ListField(child=serializers.CharField(), required=False, help_text="Spots it leaves out.")
    then = serializers.JSONField(
        required=False, help_text="What it says to do: a branch, or a list of branches each with its own test."
    )
    basis = serializers.CharField(required=False, help_text='"exact" for a card that works the price out.')


class NumbersSerializer(serializers.Serializer):
    """The numbers behind a decision, as practice.spots works them out. Amounts are chips."""

    street = serializers.CharField()
    facing = serializers.ChoiceField(choices=["none", "bet", "raise"])
    bettor = serializers.CharField(allow_null=True)
    bet = serializers.IntegerField(allow_null=True, help_text="Chips put in with the bet or raise faced.")
    pot_before = serializers.IntegerField(allow_null=True, help_text="Everything in the middle before it.")
    to_call = serializers.IntegerField()
    pot = serializers.IntegerField(help_text="Everything in the middle now.")
    pot_if_call = serializers.IntegerField(help_text="The pot after a call that you can win.")
    equity_needed = serializers.FloatField(allow_null=True)
    mdf = serializers.FloatField(allow_null=True)
    effective_bb = serializers.FloatField()
    spr = serializers.FloatField(allow_null=True)
    players = serializers.IntegerField()
    position = serializers.ChoiceField(choices=["in", "out"], allow_null=True)
    hand_class = serializers.ChoiceField(choices=["nothing", "draw", "showdown_value", "strong"], allow_null=True)
    made = serializers.CharField(allow_null=True)
    draws = serializers.ListField(child=serializers.CharField())
    in_front = serializers.IntegerField()
    big_blind = serializers.IntegerField()


class HandResultSerializer(serializers.Serializer):
    hand = serializers.IntegerField(
        allow_null=True, help_text="The hand's id, for its replay; null for a hand shared with your class."
    )
    step = serializers.IntegerField(help_text="The event the decision is.")
    net_bb = serializers.FloatField(help_text="How the hand went for you, in big blinds.")


class ChartSerializer(serializers.Serializer):
    """The published chart a preflop spot is graded by, and the tier of it the spot is in (practice.charts)."""

    key = serializers.CharField()
    label = serializers.CharField()
    applies_to = serializers.CharField(help_text="The stacks and table the chart is for.")
    source = serializers.CharField()
    tier = serializers.CharField()
    range = serializers.CharField(help_text="The tier's hands, in range notation.")
    tier_label = serializers.CharField()
    claimed = serializers.CharField(help_text="What the lecture calls its size, rounded for teaching.")
    tier_source = serializers.CharField()
    share = serializers.FloatField(help_text="Its exact share of all 1,326 combos.")


class AnchorSerializer(serializers.Serializer):
    """The course's memory aid nearest a stated share of hands [MIT 4], and how much of the answer it holds."""

    percent = serializers.IntegerField()
    range = serializers.CharField()
    overlap = serializers.FloatField(help_text="Combos in both ÷ combos in either.")


class FeedbackSerializer(serializers.Serializer):
    """The answer, shown once a spot is answered. Which fields appear depends on the question and the grading."""

    correct = serializers.IntegerField(required=False, help_text="A choice: the right option's index.")
    value = serializers.FloatField(required=False, help_text="A choice: the exact value.")
    formula = serializers.CharField(required=False)
    explanation = serializers.CharField(required=False)
    amounts = AmountsField()
    best = serializers.ListField(child=serializers.ChoiceField(choices=ACTIONS), required=False)
    acceptable = serializers.ListField(
        child=serializers.ChoiceField(choices=ACTIONS),
        required=False,
        help_text="A chart's spot: moves worth half credit, such as limping a hand the chart raises.",
    )
    ev_bb = serializers.DictField(child=serializers.FloatField(), required=False, help_text="Each option's EV in bb.")
    equity = serializers.FloatField(required=False)
    equity_needed = serializers.FloatField(required=False)
    range = serializers.CharField(
        required=False, help_text="The stated range the answer assumes, or a range question's answer."
    )
    chart = ChartSerializer(required=False, help_text="A preflop spot: the chart and tier it is graded by.")
    hand = serializers.CharField(required=False, help_text="A preflop spot: your hand, as the chart names it.")
    in_range = serializers.BooleanField(required=False, help_text="A preflop spot: whether the chart plays your hand.")
    share = serializers.FloatField(required=False, help_text="A range question: the range's share of all combos.")
    percent = serializers.IntegerField(required=False, help_text="A range question: the share stated with the spot.")
    anchor = AnchorSerializer(required=False)
    assumptions = serializers.CharField(required=False)
    advice = AdviceSerializer(required=False, allow_null=True)
    rule = RuleCardSerializer(required=False, allow_null=True)
    you_did = MoveSerializer(required=False, help_text="Your own hand: what you did at the time.")
    player = serializers.CharField(required=False, help_text="Their seat: the player whose seat it was.")
    they_did = MoveSerializer(required=False, help_text="Their seat: what they did at the time.")
    their_cards = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Their range: the cards they showed."
    )
    their_hand = serializers.CharField(required=False, help_text="Their range: those cards as a hand, 97s.")
    in_stated = serializers.BooleanField(required=False, help_text="Their range: their hand was in the stated range.")
    result = HandResultSerializer(required=False)
    context = NumbersSerializer(required=False)


class OverlapSerializer(serializers.Serializer):
    """How a range answer met the stated range, in combos."""

    both = serializers.IntegerField(help_text="In your range and the stated one.")
    extra = serializers.IntegerField(help_text="In your range only.")
    missed = serializers.IntegerField(help_text="In the stated range only.")


class OutcomeSerializer(serializers.Serializer):
    """Once a spot from one of your hands is answered: the hand from the spot's seat, to the end."""

    hand = TableHandSerializer(
        help_text="The spot's events up to its decision, then every one after it: the move made at the table, the "
        "cards to come, the showdown, and each player's result."
    )
    decision = serializers.IntegerField(
        help_text="The replay step the spot asked at: the table as it stood. The next step is the move made then."
    )


# Spots from the user's own hands, which they may see to the end once answered: not a hand shared with them.
OUTCOME_SOURCES = ("own_hand", "their_seat")


class AttemptResultSerializer(serializers.ModelSerializer):
    """A graded answer, with the spot's answer. A reflection is not graded: its grade is "ungraded"."""

    answer = FeedbackSerializer(source="scenario.answer")
    outcome = serializers.SerializerMethodField(
        help_text="A spot from one of your hands, My hands' or their seat's: what was played there and how it ended."
    )
    grading = serializers.ChoiceField(source="scenario.grading", choices=list(Scenario.GRADINGS))
    overlap = serializers.SerializerMethodField(help_text="A range answer: how it met the stated range.")

    class Meta:
        model = Attempt
        fields = (
            "id",
            "scenario",
            "choice",
            "hand_range",
            "overlap",
            "action",
            "amount",
            "reason",
            "confidence",
            "grade",
            "score",
            "weight",
            "ev_lost_bb",
            "rule",
            "grading",
            "answer",
            "outcome",
            "created",
        )
        read_only_fields = fields

    @extend_schema_field(OutcomeSerializer(allow_null=True))
    def get_outcome(self, attempt):
        scenario = attempt.scenario
        if scenario.source not in OUTCOME_SOURCES or not scenario.hand_id or scenario.step is None:
            return None
        hero = (scenario.spec.get("hand") or {}).get("hero") or scenario.hand.hero
        return OutcomeSerializer(outcome_of(hand_data(scenario.hand), scenario.step, hero)).data

    @extend_schema_field(OverlapSerializer(allow_null=True))
    def get_overlap(self, attempt):
        if attempt.scenario.spec["question"]["kind"] != "range":
            return None
        stated = ranges.parse(attempt.scenario.answer["range"])
        return charts.overlap(ranges.parse(attempt.hand_range), stated)


class RangeField(serializers.CharField):
    """Hands in range notation, as hands.ranges reads it: "TT+, AQs+, AKo"."""

    def to_internal_value(self, data):
        notation = super().to_internal_value(data)
        try:
            ranges.parse(notation)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from None
        return notation


class AnswerSerializer(serializers.Serializer):
    """An answer to a spot: a choice, a range of hands, or a move."""

    choice = serializers.IntegerField(required=False, min_value=0, max_value=3)
    hand_range = RangeField(
        required=False, allow_blank=True, max_length=2000, help_text="A range question: the hands, in range notation."
    )
    action = serializers.ChoiceField(choices=ACTIONS, required=False)
    amount = serializers.IntegerField(required=False, min_value=1, help_text="A bet or raise: the bet it makes.")
    reason = serializers.ChoiceField(choices=REASONS, required=False)
    confidence = serializers.IntegerField(required=False, min_value=1, max_value=5)
    time_taken = serializers.FloatField(required=False, min_value=0)
    tz = TimeZoneField(required=False, default=UTC, help_text="The time zone the user's days are counted in.")

    @staticmethod
    def check(scenario, attrs):
        """The answer the spot's question asks for, and a bet or raise's amount."""
        kind = scenario.spec["question"]["kind"]
        if kind == "choice" and "choice" not in attrs:
            raise serializers.ValidationError({"choice": "This spot asks for a choice."})
        if kind == "range" and "hand_range" not in attrs:
            raise serializers.ValidationError({"hand_range": "This spot asks for a range of hands."})
        if kind == "action" and "action" not in attrs:
            raise serializers.ValidationError({"action": "This spot asks what you do."})
        if attrs.get("action") in ("bet", "raise") and "amount" not in attrs:
            raise serializers.ValidationError({"amount": "A bet or raise needs its amount."})


class AttemptRequestSerializer(AnswerSerializer):
    scenario = serializers.PrimaryKeyRelatedField(queryset=Scenario.objects.all())
    set = serializers.PrimaryKeyRelatedField(queryset=ScenarioSet.objects.all(), required=False, allow_null=True)

    def validate(self, attrs):
        user = self.context["request"].user
        scenario, practice_set = attrs["scenario"], attrs.get("set")
        if not shared.open_to(user, scenario):
            raise serializers.ValidationError({"scenario": "Not found."})
        if practice_set and (practice_set.user_id != user.pk or not practice_set.items.filter(scenario=scenario)):
            raise serializers.ValidationError({"set": "Not one of your sets with this spot."})
        if practice_set and practice_set.kind == "test":
            raise serializers.ValidationError({"set": "A test's answers go to the test."})
        self.check(scenario, attrs)
        return attrs


class ReviewRequestSerializer(serializers.Serializer):
    scenario = serializers.PrimaryKeyRelatedField(queryset=Scenario.objects.all())
    tz = TimeZoneField(required=False, default=UTC)


class ReviewSerializer(serializers.Serializer):
    scenario = serializers.IntegerField(source="scenario_id")
    box = serializers.IntegerField(help_text="Its Leitner box: 1 comes back tomorrow, 5 in a month.")
    due = serializers.DateField()


class SpotSerializer(serializers.Serializer):
    """A spot in a set, and the answer given to it in the set, if any."""

    position = serializers.IntegerField()
    review = serializers.BooleanField(help_text="A spot coming back from an earlier miss or an \"again later\".")
    scenario = ScenarioSerializer()
    attempt = AttemptResultSerializer(allow_null=True)


class PracticeSetSerializer(serializers.ModelSerializer):
    spots = SpotSerializer(many=True)

    class Meta:
        model = ScenarioSet
        fields = ("id", "kind", "day", "skill", "created", "finished", "spots")
        read_only_fields = fields


class NewSetSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["my_hands", "generated", "library", "their_seat", "shared"],
        help_text=(
            "Your own decisions, generated spots for one skill, worked examples from the lectures, your opponents' "
            "decisions in your hands, from their seat, or decisions in hands shared with your classes."
        ),
    )
    skill = serializers.ChoiceField(choices=SKILL_CHOICES, required=False, help_text="A generated set's skill.")
    tz = TimeZoneField(required=False, default=UTC)

    def validate(self, attrs):
        if attrs["kind"] == "generated" and "skill" not in attrs:
            raise serializers.ValidationError({"skill": "A generated set needs its skill."})
        if attrs["kind"] == "shared" and not settings.CLASSES_ENABLED:
            raise serializers.ValidationError({"kind": "Classes aren't open yet: no shared hands to practise."})
        return attrs


class RatingSerializer(serializers.Serializer):
    """A Glicko rating (practice.ratings): 1,500 to start, its deviation the uncertainty, and its 95% range."""

    rating = serializers.IntegerField()
    deviation = serializers.IntegerField()
    low = serializers.IntegerField()
    high = serializers.IntegerField()
    attempts = serializers.IntegerField(help_text="Graded answers it rests on.")


class SkillScoreSerializer(serializers.Serializer):
    """A skill's weighted share of good answers, with its 95% Wilson range: a rule of thumb counts half."""

    skill = serializers.ChoiceField(choices=SKILL_CHOICES)
    label = serializers.CharField()
    attempts = serializers.IntegerField(help_text="Every answer, reflections included.")
    did = serializers.FloatField(help_text="Good answers, weighted.")
    could = serializers.FloatField(help_text="Graded answers, weighted.")
    pct = serializers.FloatField(allow_null=True)
    ci_low = serializers.FloatField(allow_null=True)
    ci_high = serializers.FloatField(allow_null=True)
    rating = RatingSerializer(
        allow_null=True, help_text="Its rating against the spots' difficulty, once its range is narrow enough to show."
    )


class PracticeDaySerializer(serializers.Serializer):
    day = serializers.DateField()
    attempts = serializers.IntegerField()


class GeneratedSkillSerializer(serializers.Serializer):
    skill = serializers.ChoiceField(choices=SKILL_CHOICES)
    label = serializers.CharField()


class PracticeProfileSerializer(serializers.Serializer):
    skills = SkillScoreSerializer(many=True)
    days = PracticeDaySerializer(many=True, help_text="Days with answers, oldest first.")
    current_streak = serializers.IntegerField()
    best_streak = serializers.IntegerField()
    today = serializers.DateField()
    reviews_due = serializers.IntegerField(help_text="Spots due back today or earlier.")
    generated = GeneratedSkillSerializer(many=True, help_text="The skills generated sets can drill.")


class PlaybookSerializer(serializers.ModelSerializer):
    """A named, versioned list of rule cards: a house preset, one of your own, or one a coach assigned your class."""

    house = serializers.SerializerMethodField(help_text="A house preset, rather than one a user wrote.")
    rule_count = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField(help_text="Who wrote it; null for a house preset.")
    mine = serializers.SerializerMethodField(help_text="Your own: you can edit it and assign it to your classes.")
    classes = serializers.SerializerMethodField(help_text="Your own: the classes it is assigned to now.")

    class Meta:
        model = Playbook
        fields = (
            "id", "key", "name", "version", "game", "format", "description", "house", "rule_count", "author", "mine",
            "classes", "archived",
        )
        read_only_fields = fields

    def get_house(self, playbook) -> bool:
        return playbook.owner_id is None

    def get_rule_count(self, playbook) -> int:
        return len(playbook.rules)

    def get_author(self, playbook) -> str | None:
        return playbook.owner.username if playbook.owner_id else None

    def get_mine(self, playbook) -> bool:
        return playbook.owner_id == self.context["request"].user.pk

    def get_classes(self, playbook) -> list[str]:
        if not self.get_mine(playbook):
            return []
        listed = self.context.get("classes")  # a list's: coaching.classes_by_playbook, read once for every row
        if listed is None:
            return coaching.classes_of(playbook)
        return listed.get((playbook.owner_id, playbook.key), [])


class FamilyStageSerializer(serializers.Serializer):
    """How far the coach has handed a rule family over: 1 watch, 2 call it, 3 play then hear it, 4 solo."""

    family = serializers.ChoiceField(choices=list(FAMILIES))
    label = serializers.CharField()
    stage = serializers.IntegerField(min_value=1, max_value=4)
    recent = serializers.ListField(
        child=serializers.BooleanField(),
        help_text="The family's last decisions a rule settled, oldest first: kept without asking the coach, or not.",
    )


class PlaybookDetailSerializer(PlaybookSerializer):
    rules = RuleCardSerializer(many=True)
    families = FamilyStageSerializer(many=True)
    latest = serializers.SerializerMethodField(help_text="This is its latest version: the one to edit.")

    class Meta(PlaybookSerializer.Meta):
        fields = (*PlaybookSerializer.Meta.fields, "rules", "families", "latest")
        read_only_fields = fields

    def get_latest(self, playbook) -> bool:
        return coaching.latest(playbook).pk == playbook.pk


class PlaybookCopySerializer(serializers.Serializer):
    """A playbook of your own, to edit: a copy of one you can read."""

    copy_of = serializers.PrimaryKeyRelatedField(queryset=Playbook.objects.all())
    name = serializers.CharField(max_length=100)

    def validate_copy_of(self, playbook):
        if not coaching.can_read(self.context["request"].user, playbook):
            raise serializers.ValidationError("Not found.")
        return playbook


class PlaybookVersionSerializer(serializers.Serializer):
    """Your playbook's next version: its name and description, and every card, checked as the rule engine reads it."""

    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=1000, allow_blank=True)
    rules = serializers.ListField(child=serializers.DictField(), help_text="The cards, in order: RuleCard's fields.")


class ConditionSerializer(serializers.Serializer):
    """Something a card's test can ask of a decision."""

    key = serializers.CharField()
    kind = serializers.ChoiceField(choices=["choice", "bool", "number", "line"])
    label = serializers.CharField()
    choices = serializers.ListField(child=serializers.CharField(), required=False)
    low = serializers.FloatField(required=False)
    high = serializers.FloatField(required=False)


class NamedSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class PlaybookVocabularySerializer(serializers.Serializer):
    """What a coach's cards can say: the tests, families, scopes, reads, actions and exceptions the engine knows."""

    conditions = ConditionSerializer(many=True)
    families = NamedSerializer(many=True)
    scopes = NamedSerializer(many=True)
    reads = NamedSerializer(many=True)
    actions = serializers.ListField(child=serializers.CharField())
    unless = NamedSerializer(many=True)


class BookQuerySerializer(serializers.Serializer):
    playbook = serializers.PrimaryKeyRelatedField(queryset=Playbook.objects.all())
    rule = serializers.CharField(required=False, help_text="A card's id: also list the decisions it applied to.")

    def validate(self, attrs):
        playbook = attrs["playbook"]
        if not coaching.can_read(self.context["request"].user, playbook):
            raise serializers.ValidationError({"playbook": "Not found."})
        cards = {card["id"]: card for card in playbook.rules}
        if "rule" in attrs and attrs["rule"] not in cards:
            raise serializers.ValidationError({"rule": "Not one of the playbook's cards."})
        if cards.get(attrs.get("rule"), {}).get("adjustment"):
            raise serializers.ValidationError({"rule": "An adjustment isn't counted by the book: it needs a read."})
        return attrs


class BookRuleSerializer(serializers.Serializer):
    """How often a rule was kept when it applied, with its 95% Wilson range."""

    rule = serializers.CharField()
    did = serializers.IntegerField(help_text="Decisions that kept it.")
    could = serializers.IntegerField(help_text="Decisions it applied to.")
    pct = serializers.FloatField(allow_null=True)
    ci_low = serializers.FloatField(allow_null=True)
    ci_high = serializers.FloatField(allow_null=True)


class BookChanceSerializer(serializers.Serializer):
    """A decision in one of the user's hands that a rule applied to."""

    hand = serializers.IntegerField(help_text="The hand's id, for its replay.")
    hand_id = serializers.CharField(help_text="The site's hand number.")
    played_at = serializers.DateTimeField()
    step = serializers.IntegerField(help_text="The event the decision is: open the replay there.")
    street = serializers.CharField()
    move = MoveSerializer()
    followed = serializers.BooleanField()


class BookSerializer(serializers.Serializer):
    """By the book: the playbook's default rules over the user's recent hands, at least a day old."""

    hands = serializers.IntegerField(help_text="How many of the user's hands were looked at, the most recent first.")
    rules = BookRuleSerializer(many=True)
    chances = BookChanceSerializer(many=True, required=False, help_text="With `rule`: where it applied.")


# Coached matches ----------------------------------------------------------------------------------------------

STYLES = ["tag", "lag", "station", "rock"]
AUTHORS = ["coach", "user"]
NOTE_TAGS = [*TAGS, *ONE_OFF]
DEPARTURES = ["read", "price", "stack", "felt"]


class MatchStartSerializer(serializers.Serializer):
    opponent = serializers.ChoiceField(
        choices=CoachedMatch.OPPONENTS,
        default="mystery",
        help_text="A style to drill one adjustment against, or a mystery: a random style. The leak is always hidden.",
    )
    coach = serializers.ChoiceField(
        choices=CoachedMatch.COACH,
        default="progress",
        help_text='"progress" follows your stage in each rule family; "1" to "4" pins the coach to a stage.',
    )
    playbook = serializers.PrimaryKeyRelatedField(
        queryset=Playbook.objects.all(), required=False, help_text="The house starter playbook if left out."
    )

    def validate_playbook(self, playbook):
        if not coaching.can_read(self.context["request"].user, playbook):
            raise serializers.ValidationError("Not found.")
        return playbook


class MoveRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ACTIONS)
    amount = serializers.IntegerField(required=False, min_value=1, help_text="A bet or raise: the bet it makes.")
    reason = serializers.ChoiceField(choices=REASONS, required=False)

    def validate(self, attrs):
        if attrs["action"] in ("bet", "raise") and "amount" not in attrs:
            raise serializers.ValidationError({"amount": "A bet or raise needs its amount."})
        return attrs


class ActRequestSerializer(MoveRequestSerializer):
    time_taken = serializers.FloatField(required=False, min_value=0, help_text="Seconds the decision took.")


class IntentRequestSerializer(MoveRequestSerializer):
    """Stage 2: what you would do here, and why. The reason is required."""

    reason = serializers.ChoiceField(choices=REASONS)


class DepartureRequestSerializer(serializers.Serializer):
    hand = serializers.IntegerField(min_value=1, help_text="The hand's number in the match.")
    step = serializers.IntegerField(min_value=0)
    why = serializers.ChoiceField(
        choices=DEPARTURES, help_text="A read on them, the price, the stack depth, or it felt right."
    )


class NoteRequestSerializer(serializers.Serializer):
    """A note on the read card: what a showdown told you, a read, or a label for their style."""

    kind = serializers.ChoiceField(choices=["showdown", "read", "label"])
    tag = serializers.CharField(help_text="A read's or showdown's tag (a read card tag), or a style for a label.")
    hand = serializers.IntegerField(required=False, min_value=1, help_text="A showdown note: the hand's number.")
    withdraw = serializers.BooleanField(default=False, help_text="A read: take it off the card.")

    def validate(self, attrs):
        kind, tag = attrs["kind"], attrs["tag"]
        allowed = STYLES if kind == "label" else NOTE_TAGS if kind == "showdown" else list(TAGS)
        if tag not in allowed:
            raise serializers.ValidationError({"tag": f"Not a {kind} tag."})
        if kind == "showdown" and "hand" not in attrs:
            raise serializers.ValidationError({"hand": "A showdown note needs its hand."})
        return attrs


class IntentSerializer(serializers.Serializer):
    """What you said you would do at stage 2, and what the coach made of it."""

    action = serializers.ChoiceField(choices=ACTIONS)
    amount = serializers.IntegerField(allow_null=True)
    reason = serializers.CharField(allow_blank=True)
    kept = serializers.BooleanField(help_text="It keeps the playbook.")
    line = serializers.CharField(help_text="The coach's answer.")
    reason_fits = serializers.BooleanField()
    reason_note = serializers.CharField(allow_blank=True, help_text="Why the reason doesn't fit, when it doesn't.")


class DecisionViewSerializer(serializers.Serializer):
    """The decision you face, and as much of the coach's advice as its stage allows yet."""

    step = serializers.IntegerField()
    stage = serializers.IntegerField(help_text="1 watch, 2 call it, 3 play then hear it, 4 solo.")
    stage_name = serializers.CharField()
    family = serializers.ChoiceField(choices=list(FAMILIES))
    family_label = serializers.CharField()
    situation = serializers.CharField(help_text="The spot in a line.")
    prompt = serializers.CharField(allow_null=True, help_text="What the coach says now; null when it is quiet.")
    advice = AdviceSerializer(allow_null=True, help_text="Sent at stage 1, after your intent at 2, or when asked.")
    rule = RuleCardSerializer(allow_null=True, help_text="The rule in play, when the advice is sent.")
    intent = IntentSerializer(allow_null=True)
    asked = serializers.BooleanField(help_text="You asked the coach, which counts against handing it over.")


class AfterHandSerializer(serializers.Serializer):
    step = serializers.IntegerField()
    line = serializers.CharField()


class DepartureSerializer(serializers.Serializer):
    """A decision that left a clear rule, which the coach asks about once."""

    hand = serializers.IntegerField()
    step = serializers.IntegerField()
    rule = serializers.CharField(allow_null=True)
    street = serializers.CharField()


class ReadCountSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    did = serializers.IntegerField()
    could = serializers.IntegerField(help_text="Chances: 0 says the count tells nothing yet.")


class NoteSerializer(serializers.Serializer):
    tag = serializers.CharField()
    by = serializers.ChoiceField(choices=AUTHORS)


class ShowdownSerializer(serializers.Serializer):
    """A hand that showed their cards, read backwards: their biggest move and what they held."""

    number = serializers.IntegerField(help_text="The hand's number in the match.")
    cards = serializers.ListField(child=serializers.CharField())
    line = serializers.CharField()
    offer = serializers.ListField(child=serializers.CharField(), help_text="The tags that fit: what did that tell you?")
    note = NoteSerializer(allow_null=True)


class ReadSerializer(serializers.Serializer):
    tag = serializers.CharField()
    label = serializers.CharField()
    by = serializers.ChoiceField(choices=AUTHORS)
    hand = serializers.IntegerField(allow_null=True, help_text="The hand it was written after.")
    evidence = serializers.ChoiceField(
        choices=["thin", "strong"], allow_null=True, help_text="How much backs it: thin evidence only tips close calls."
    )


class LabelSerializer(serializers.Serializer):
    style = serializers.ChoiceField(choices=STYLES)
    vpip = serializers.IntegerField()
    aggression = serializers.IntegerField()
    hands = serializers.IntegerField()


class AcceptedSerializer(serializers.Serializer):
    style = serializers.ChoiceField(choices=STYLES)
    by = serializers.ChoiceField(choices=AUTHORS)


class TagSerializer(serializers.Serializer):
    tag = serializers.CharField()
    label = serializers.CharField()


class ReadCardSerializer(serializers.Serializer):
    """A notebook on the opponent, from what the table showed: counts, showdowns, reads and a label."""

    hands = serializers.IntegerField()
    counts = ReadCountSerializer(many=True)
    showdowns = ShowdownSerializer(many=True)
    reads = ReadSerializer(many=True)
    label = LabelSerializer(allow_null=True, help_text="The style the counts propose, once they allow.")
    accepted = AcceptedSerializer(allow_null=True)
    tags = TagSerializer(many=True, help_text="The reads the card can hold.")


class MatchStateSerializer(serializers.Serializer):
    """A coached match as you see it. Amounts are chips; the bot's style and leak wait for the debrief."""

    id = serializers.IntegerField()
    opponent = serializers.ChoiceField(choices=CoachedMatch.OPPONENTS, help_text="As chosen.")
    coach = serializers.ChoiceField(choices=CoachedMatch.COACH)
    playbook = serializers.IntegerField()
    started = serializers.DateTimeField()
    finished = serializers.DateTimeField(allow_null=True)
    hand_number = serializers.IntegerField()
    hands_planned = serializers.IntegerField()
    small_blind = serializers.IntegerField()
    big_blind = serializers.IntegerField()
    next_level_in = serializers.IntegerField(help_text="Hands until the blinds go up.")
    hand = TableHandSerializer()
    hand_over = serializers.BooleanField()
    hand_net_bb = serializers.FloatField(allow_null=True)
    legal = LegalSerializer(allow_null=True, help_text="Your moves, when it is your turn.")
    decision = DecisionViewSerializer(allow_null=True)
    after_hand = AfterHandSerializer(allow_null=True, help_text="Stage 3: the coach's comment once the hand is over.")
    departure = DepartureSerializer(allow_null=True, help_text="A rule you left, which the coach asks about once.")
    read = ReadCardSerializer()
    time_bank = serializers.FloatField(help_text="Seconds left in the match's time bank.")
    result_bb = serializers.FloatField(help_text="Chips won by the last hand over, in starting big blinds.")


class MatchSummarySerializer(serializers.ModelSerializer):
    hands_played = serializers.IntegerField(source="table.hands_played")

    class Meta:
        model = CoachedMatch
        fields = ("id", "opponent", "coach", "started", "finished", "hands_planned", "hands_played", "result_bb")
        read_only_fields = fields


class DebriefDecisionSerializer(serializers.Serializer):
    """A decision the debrief points to: the table as it stood, and what the coach would have said."""

    table = TableHandSerializer(help_text="The hand up to the decision.")
    line = serializers.CharField(help_text="The coach's line on it.")
    hand = serializers.IntegerField()
    step = serializers.IntegerField()
    street = serializers.CharField()
    holding = serializers.CharField(allow_blank=True)
    cards = serializers.ListField(child=serializers.CharField())
    pot_bb = serializers.FloatField()
    advice = AdviceSerializer()
    move = MoveSerializer(allow_null=True)
    followed = serializers.BooleanField(allow_null=True)
    departure = serializers.CharField(allow_blank=True)
    asked = serializers.BooleanField()


class FixSerializer(serializers.Serializer):
    family = serializers.ChoiceField(choices=list(FAMILIES))
    label = serializers.CharField()
    misses = serializers.IntegerField()
    rule = RuleCardSerializer(allow_null=True)
    decision = DebriefDecisionSerializer()


class PickedHandSerializer(DebriefDecisionSerializer):
    kind = serializers.ChoiceField(choices=["departure", "best", "closest"])


class TruthSerializer(serializers.Serializer):
    """The bot revealed beside your card."""

    style = serializers.ChoiceField(choices=STYLES)
    leak = serializers.CharField()
    leak_label = serializers.CharField()
    leak_tag = serializers.CharField(help_text="The read that finds the leak.")
    label = serializers.CharField(allow_null=True, help_text="The label on the card at the end.")
    label_right = serializers.BooleanField()
    label_hand = serializers.IntegerField(allow_null=True, help_text="The hand the right label came after.")
    reads = serializers.ListField(child=serializers.CharField())
    found = serializers.BooleanField()
    found_hand = serializers.IntegerField(allow_null=True)
    found_by = serializers.ChoiceField(choices=AUTHORS, allow_null=True)
    wrong = serializers.ListField(
        child=serializers.CharField(), help_text="The reads on the card the bot didn't have, in words."
    )


class AllInSerializer(serializers.Serializer):
    hand = serializers.IntegerField()
    equity = serializers.FloatField()
    expected_bb = serializers.FloatField()
    net_bb = serializers.FloatField()


class LuckSerializer(serializers.Serializer):
    """Chips won against chips expected, in starting big blinds."""

    actual_bb = serializers.FloatField(help_text="Chips won.")
    expected_bb = serializers.FloatField(help_text="Chips expected when the money went in.")
    luck_bb = serializers.FloatField(help_text="The gap: above expectation when positive.")
    all_ins = AllInSerializer(many=True)
    coolers = serializers.ListField(
        child=serializers.IntegerField(), help_text="Hands lost by a stack with every decision by the book."
    )


class MovedSerializer(serializers.Serializer):
    family = serializers.ChoiceField(choices=list(FAMILIES))
    label = serializers.CharField()
    start = serializers.IntegerField(source="from")
    end = serializers.IntegerField(source="to")


class SentSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Decisions that left a rule, now spots in your daily sets.")
    due = serializers.DateField()


class DebriefSerializer(serializers.Serializer):
    fix = FixSerializer(allow_null=True, help_text="One thing to fix: none after a match by the book.")
    hands = PickedHandSerializer(many=True)
    book = BookRuleSerializer(many=True)
    read = TruthSerializer()
    luck = LuckSerializer()
    pinned = serializers.BooleanField(help_text="The coach was pinned to a stage, so no family moved.")
    moved = MovedSerializer(many=True)
    sent = SentSerializer()
    result_bb = serializers.FloatField(allow_null=True)
    hands_played = serializers.IntegerField()


# The aptitude test -------------------------------------------------------------------------------------------------


class TestAnswerSerializer(AnswerSerializer):
    """An answer to the spot a test is asking. Its grade waits for the end of the test."""

    scenario = serializers.PrimaryKeyRelatedField(queryset=Scenario.objects.all())

    def validate(self, attrs):
        self.check(attrs["scenario"], attrs)
        return attrs


class TestSpotSerializer(serializers.Serializer):
    position = serializers.IntegerField()
    scenario = ScenarioSerializer()


class TestStateSerializer(serializers.Serializer):
    """A test as it goes: how far it has got, and the spot it asks now, without any answers."""

    id = serializers.IntegerField()
    planned = serializers.IntegerField(help_text="Spots in the test.")
    answered = serializers.IntegerField()
    started = serializers.DateTimeField(source="created")
    finished = serializers.DateTimeField(allow_null=True)
    spot = TestSpotSerializer(allow_null=True, help_text="The spot to answer now; null once the test is over.")


class TestSkillSerializer(serializers.Serializer):
    """A skill in the report: its accuracy in the test with its 95% range, its rating then, and the result in words."""

    skill = serializers.ChoiceField(choices=SKILL_CHOICES)
    label = serializers.CharField()
    spots = serializers.IntegerField(help_text="Spots in the test that tested it.")
    did = serializers.FloatField(help_text="Good answers, weighted: a rule of thumb counts half.")
    could = serializers.FloatField()
    pct = serializers.FloatField(allow_null=True)
    ci_low = serializers.FloatField(allow_null=True)
    ci_high = serializers.FloatField(allow_null=True)
    rating = RatingSerializer(allow_null=True, help_text="The rating as it stood when the test ended.")
    rating_shown = serializers.BooleanField(help_text="Its range is narrow enough to show the rating.")
    words = serializers.CharField(help_text='The result in words, with its sample: "12 spots: too few to be sure".')


class TestReportSpotSerializer(serializers.Serializer):
    position = serializers.IntegerField()
    scenario = ScenarioSerializer()
    attempt = AttemptResultSerializer(help_text="Your answer, its grade, and the spot's answer and basis.")


class PractiseNextSerializer(serializers.Serializer):
    """What to practise next: the weakest skill whose range is narrow enough to trust, else the weakest tested."""

    skill = serializers.ChoiceField(choices=SKILL_CHOICES)
    label = serializers.CharField()
    trusted = serializers.BooleanField(help_text="Its range is narrow enough to trust.")
    generated = serializers.BooleanField(help_text="Generated sets can drill it.")


class TestReportSerializer(serializers.Serializer):
    """An aptitude test once it is over: how well you decided in these spots, skill by skill."""

    id = serializers.IntegerField()
    planned = serializers.IntegerField()
    answered = serializers.IntegerField()
    started = serializers.DateTimeField()
    finished = serializers.DateTimeField()
    minutes = serializers.FloatField(allow_null=True, help_text="Time taken over the answers.")
    skills = TestSkillSerializer(many=True)
    spots = TestReportSpotSerializer(many=True)
    next = PractiseNextSerializer(allow_null=True)


class TestSummarySerializer(serializers.ModelSerializer):
    answered = serializers.IntegerField()
    started = serializers.DateTimeField(source="created")

    class Meta:
        model = ScenarioSet
        fields = ("id", "planned", "answered", "started", "finished")
        read_only_fields = fields


# Play it out -------------------------------------------------------------------------------------------------------


class TableStartSerializer(serializers.Serializer):
    """A new Play it out table: from a deal, or one of your hands played on from a spot's decision."""

    scenario = serializers.PrimaryKeyRelatedField(
        queryset=Scenario.objects.all(),
        required=False,
        help_text="A spot from one of your own hands: play that hand on from its decision. Else a fresh deal.",
    )
    seats = serializers.IntegerField(min_value=2, max_value=9, default=6, help_text="A fresh deal: seats, yours too.")
    opponents = serializers.ChoiceField(
        choices=play.OPPONENTS,
        default="mixed",
        help_text="A fresh deal: bots of one style, a mix, or modelled on your own opponents with the most hands.",
    )
    stack_bb = serializers.IntegerField(min_value=20, max_value=250, default=100, help_text="A fresh deal: stacks.")

    def validate_scenario(self, scenario):
        if scenario.owner_id != self.context["request"].user.pk:
            raise serializers.ValidationError("Not found.")
        return scenario


class TableMoveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ACTIONS)
    amount = serializers.IntegerField(required=False, min_value=1, help_text="A bet or raise: the bet it makes.")

    def validate(self, attrs):
        if attrs["action"] in ("bet", "raise") and "amount" not in attrs:
            raise serializers.ValidationError({"amount": "A bet or raise needs its amount."})
        return attrs


class BasedOnSerializer(serializers.Serializer):
    """The opponent of yours a bot was modelled on, from their statistics in your hands."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    hands = serializers.IntegerField(help_text="Hands with you behind the model.")


class TableSeatSerializer(serializers.Serializer):
    seat = serializers.IntegerField()
    name = serializers.CharField()
    hero = serializers.BooleanField()
    label = serializers.CharField(allow_blank=True, help_text="What the bot is: a style, or who it was modelled on.")
    style = serializers.CharField(allow_blank=True, help_text="A style bot's style; empty for a modelled one.")
    based_on = BasedOnSerializer(allow_null=True)


class TableSpotSerializer(serializers.Serializer):
    """Where a table played on from a spot stands."""

    scenario = serializers.IntegerField()
    hand = serializers.IntegerField(help_text="Your hand it plays on, for its replay.")
    step = serializers.IntegerField(help_text="The decision it started from.")
    on_script = serializers.BooleanField(help_text="The others still replay what they did, your line matching theirs.")


class PlayTableSerializer(serializers.Serializer):
    """A Play it out table as you see it: the hand so far, your moves when it is your turn, and who the bots are."""

    id = serializers.IntegerField()
    hand_number = serializers.IntegerField()
    hands_played = serializers.IntegerField()
    small_blind = serializers.IntegerField()
    big_blind = serializers.IntegerField()
    hand = TableHandSerializer()
    hand_over = serializers.BooleanField()
    hand_net_bb = serializers.FloatField(allow_null=True)
    legal = LegalSerializer(allow_null=True, help_text="Your moves, when it is your turn.")
    seats = TableSeatSerializer(many=True)
    result_bb = serializers.FloatField(help_text="Your chips won since you sat down, in big blinds, rebuys aside.")
    spot = TableSpotSerializer(allow_null=True, help_text="A table played on from a spot: where it stands.")


class PlayTableSummarySerializer(serializers.ModelSerializer):
    hands = serializers.IntegerField(source="dealt", help_text="Hands dealt.")
    players = serializers.SerializerMethodField()
    from_spot = serializers.SerializerMethodField()

    class Meta:
        model = PracticeTable
        fields = ("id", "created", "updated", "hands", "players", "from_spot")
        read_only_fields = fields

    def get_players(self, table) -> int:
        return len(table.seats)

    def get_from_spot(self, table) -> bool:
        return table.scenario_id is not None
