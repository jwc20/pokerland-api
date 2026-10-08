from rest_framework import serializers

from hands.filters import UTC
from hands.serializers import HandEventSerializer, HandPlayerSerializer, TimeZoneField
from practice.models import Attempt, CoachedMatch, Playbook, Scenario, ScenarioSet
from practice.playbook import FAMILIES, READS
from practice.reads import ONE_OFF, TAGS
from practice.sets import GENERATED, SKILLS

ACTIONS = ["fold", "check", "call", "bet", "raise"]
SKILL_CHOICES = list(SKILLS)
GENERATED_SKILLS = list(GENERATED)
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
    kind = serializers.ChoiceField(choices=["action", "choice"], help_text="What to do, or a choice of four.")
    prompt = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField(), required=False)
    unit = serializers.ChoiceField(choices=["percent", "ratio", "number"], required=False)
    all_in_only = serializers.BooleanField(required=False, help_text="The only raise is all-in: push or fold.")
    amounts = AmountsField()


class ScenarioSpecSerializer(serializers.Serializer):
    """What the client draws and asks; the answer stays on the server until an attempt."""

    hand = TableHandSerializer()
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
    hand = serializers.IntegerField(help_text="The hand's id, for its replay.")
    step = serializers.IntegerField(help_text="The event the decision is.")
    net_bb = serializers.FloatField(help_text="How the hand went for you, in big blinds.")


class FeedbackSerializer(serializers.Serializer):
    """The answer, shown once a spot is answered. Which fields appear depends on the question and the grading."""

    correct = serializers.IntegerField(required=False, help_text="A choice: the right option's index.")
    value = serializers.FloatField(required=False, help_text="A choice: the exact value.")
    formula = serializers.CharField(required=False)
    explanation = serializers.CharField(required=False)
    amounts = AmountsField()
    best = serializers.ListField(child=serializers.ChoiceField(choices=ACTIONS), required=False)
    ev_bb = serializers.DictField(child=serializers.FloatField(), required=False, help_text="Each option's EV in bb.")
    equity = serializers.FloatField(required=False)
    equity_needed = serializers.FloatField(required=False)
    range = serializers.CharField(required=False, help_text="The stated range the answer assumes.")
    assumptions = serializers.CharField(required=False)
    advice = AdviceSerializer(required=False, allow_null=True)
    rule = RuleCardSerializer(required=False, allow_null=True)
    you_did = MoveSerializer(required=False, help_text="Your own hand: what you did at the time.")
    result = HandResultSerializer(required=False)
    context = NumbersSerializer(required=False)


class AttemptResultSerializer(serializers.ModelSerializer):
    """A graded answer, with the spot's answer. A reflection is not graded: its grade is "ungraded"."""

    answer = FeedbackSerializer(source="scenario.answer")
    grading = serializers.ChoiceField(source="scenario.grading", choices=list(Scenario.GRADINGS))

    class Meta:
        model = Attempt
        fields = (
            "id",
            "scenario",
            "choice",
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
            "created",
        )
        read_only_fields = fields


class AttemptRequestSerializer(serializers.Serializer):
    scenario = serializers.PrimaryKeyRelatedField(queryset=Scenario.objects.all())
    set = serializers.PrimaryKeyRelatedField(queryset=ScenarioSet.objects.all(), required=False, allow_null=True)
    choice = serializers.IntegerField(required=False, min_value=0, max_value=3)
    action = serializers.ChoiceField(choices=ACTIONS, required=False)
    amount = serializers.IntegerField(required=False, min_value=1, help_text="A bet or raise: the bet it makes.")
    reason = serializers.ChoiceField(choices=REASONS, required=False)
    confidence = serializers.IntegerField(required=False, min_value=1, max_value=5)
    time_taken = serializers.FloatField(required=False, min_value=0)
    tz = TimeZoneField(required=False, default=UTC, help_text="The time zone the user's days are counted in.")

    def validate(self, attrs):
        user = self.context["request"].user
        scenario, practice_set = attrs["scenario"], attrs.get("set")
        if scenario.owner_id not in (None, user.pk):
            raise serializers.ValidationError({"scenario": "Not found."})
        if practice_set and (practice_set.user_id != user.pk or not practice_set.items.filter(scenario=scenario)):
            raise serializers.ValidationError({"set": "Not one of your sets with this spot."})
        kind = scenario.spec["question"]["kind"]
        if kind == "choice" and "choice" not in attrs:
            raise serializers.ValidationError({"choice": "This spot asks for a choice."})
        if kind == "action" and "action" not in attrs:
            raise serializers.ValidationError({"action": "This spot asks what you do."})
        if attrs.get("action") in ("bet", "raise") and "amount" not in attrs:
            raise serializers.ValidationError({"amount": "A bet or raise needs its amount."})
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
    kind = serializers.ChoiceField(choices=["my_hands", "generated"])
    skill = serializers.ChoiceField(choices=GENERATED_SKILLS, required=False, help_text="A generated set's skill.")
    tz = TimeZoneField(required=False, default=UTC)

    def validate(self, attrs):
        if attrs["kind"] == "generated" and "skill" not in attrs:
            raise serializers.ValidationError({"skill": "A generated set needs its skill."})
        return attrs


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


class PracticeDaySerializer(serializers.Serializer):
    day = serializers.DateField()
    attempts = serializers.IntegerField()


class GeneratedSkillSerializer(serializers.Serializer):
    skill = serializers.ChoiceField(choices=GENERATED_SKILLS)
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
    """A named, versioned list of rule cards: a house preset, or one a user or coach wrote."""

    house = serializers.SerializerMethodField(help_text="A house preset, rather than one a user wrote.")
    rule_count = serializers.SerializerMethodField()

    class Meta:
        model = Playbook
        fields = ("id", "key", "name", "version", "game", "format", "description", "house", "rule_count")
        read_only_fields = fields

    def get_house(self, playbook) -> bool:
        return playbook.owner_id is None

    def get_rule_count(self, playbook) -> int:
        return len(playbook.rules)


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

    class Meta(PlaybookSerializer.Meta):
        fields = (*PlaybookSerializer.Meta.fields, "rules", "families")
        read_only_fields = fields


class BookQuerySerializer(serializers.Serializer):
    playbook = serializers.PrimaryKeyRelatedField(queryset=Playbook.objects.all())
    rule = serializers.CharField(required=False, help_text="A card's id: also list the decisions it applied to.")

    def validate(self, attrs):
        playbook = attrs["playbook"]
        if playbook.owner_id not in (None, self.context["request"].user.pk):
            raise serializers.ValidationError({"playbook": "Not found."})
        if "rule" in attrs and attrs["rule"] not in {rule["id"] for rule in playbook.rules}:
            raise serializers.ValidationError({"rule": "Not one of the playbook's cards."})
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
        if playbook.owner_id not in (None, self.context["request"].user.pk):
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
