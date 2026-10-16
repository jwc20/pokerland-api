from rest_framework import serializers

from explain import catalog
from explain.checks import ANSWER_LENGTH, QUESTION_LENGTH, ExplanationContentSerializer, Strict
from explain.models import SUBJECTS, Explanation, ExplanationTurn

PROVIDER_CHOICES = catalog.PROVIDER_NAMES
EFFORTS = ("low", "medium", "high")
ROLES = ("user", "assistant")


class ModelProviderSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=PROVIDER_CHOICES)
    label = serializers.CharField()
    company = serializers.CharField()
    key_url = serializers.URLField()
    terms_url = serializers.URLField()
    finished = serializers.CharField(help_text="The stop value the provider's API gives a finished answer.")
    notice = serializers.CharField(allow_blank=True, help_text="What the consent notice adds for this provider.")


class OfferedModelSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=PROVIDER_CHOICES)
    id = serializers.CharField()
    label = serializers.CharField()
    default = serializers.BooleanField(help_text="The provider's default model.")
    input = serializers.FloatField(help_text="US dollars per million tokens in, today.")
    output = serializers.FloatField(help_text="US dollars per million tokens out, reasoning included, today.")
    off_peak = serializers.BooleanField(help_text="Half price outside the provider's peak hours.")
    typical_hand = serializers.FloatField(help_text="About what explaining a hand costs, in US dollars.")


class CatalogSerializer(serializers.Serializer):
    prices_as_of = serializers.DateField()
    providers = ModelProviderSerializer(many=True)
    models = OfferedModelSerializer(many=True)


class SpendQuerySerializer(serializers.Serializer):
    tz = serializers.CharField(required=False, help_text="An IANA time zone for the month; UTC if not given.")


class SpendSerializer(serializers.Serializer):
    month = serializers.CharField(help_text="YYYY-MM")
    explanations = serializers.IntegerField()
    questions = serializers.IntegerField()
    cost = serializers.FloatField(help_text="About what they cost, in US dollars.")


class ExplanationSubjectSerializer(Strict):
    """What an explanation is about: a kind of subject, and its id."""

    kind = serializers.ChoiceField(choices=SUBJECTS)
    id = serializers.IntegerField(min_value=1)


class BriefRequestSerializer(ExplanationSubjectSerializer):
    """A subject, and the provider the brief is for."""

    provider = serializers.ChoiceField(choices=PROVIDER_CHOICES)


class BriefSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SUBJECTS)
    id = serializers.IntegerField()
    provider = serializers.ChoiceField(choices=PROVIDER_CHOICES)
    prompt_version = serializers.CharField()
    instructions = serializers.CharField(help_text="The system prompt.")
    input = serializers.CharField(help_text="The subject, as JSON text: the user message.")
    schema = serializers.JSONField(help_text="The JSON schema the answer must match.")
    hash = serializers.CharField(help_text="A digest of all of it, sent back with the answer.")


class TokenUsageSerializer(Strict):
    """The tokens a call used, as Pokerland prices them: `input` counts only those read afresh."""

    input = serializers.IntegerField(min_value=0, max_value=10_000_000, default=0, help_text="Read afresh.")
    cached_input = serializers.IntegerField(min_value=0, max_value=10_000_000, default=0)
    cache_write = serializers.IntegerField(min_value=0, max_value=10_000_000, default=0)
    output = serializers.IntegerField(min_value=0, max_value=10_000_000, default=0, help_text="Reasoning included.")


class WrittenSerializer(Strict):
    """What came back from a provider: who wrote it, how the call ended, and what it used."""

    provider = serializers.ChoiceField(choices=PROVIDER_CHOICES)
    model = serializers.CharField(max_length=64)
    stop = serializers.CharField(max_length=32, help_text="The provider's own stop value.")
    usage = TokenUsageSerializer()
    request_id = serializers.CharField(max_length=128, allow_blank=True, required=False, default="")

    def validate(self, data):
        if not catalog.offered(data["provider"], data["model"]):
            raise serializers.ValidationError({"model": [f"{data['model']} isn't one of the models offered."]})
        if data["stop"] != catalog.PROVIDERS[data["provider"]]["finished"]:
            raise serializers.ValidationError({"stop": ["The answer didn't finish normally, so it isn't saved."]})
        return data


class ExplanationCreateSerializer(WrittenSerializer):
    """A provider's answer to a brief, to check and save."""

    kind = serializers.ChoiceField(choices=SUBJECTS)
    id = serializers.IntegerField(min_value=1)
    brief_hash = serializers.CharField(max_length=64)
    effort = serializers.ChoiceField(choices=EFFORTS, default="medium")
    content = serializers.JSONField(help_text="The answer, parsed: explain.schema's shape.")


class ExplanationTurnSerializer(serializers.ModelSerializer):
    provider = serializers.ChoiceField(choices=PROVIDER_CHOICES, read_only=True)
    usage = TokenUsageSerializer(read_only=True)

    class Meta:
        model = ExplanationTurn
        fields = ("id", "question", "answer", "provider", "model", "usage", "cost", "created")


class ExplanationSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(choices=SUBJECTS, read_only=True)
    provider = serializers.ChoiceField(choices=PROVIDER_CHOICES, read_only=True)
    subject = serializers.SerializerMethodField(help_text="The id of what it explains; null for a rebuilt session.")
    content = ExplanationContentSerializer(read_only=True)
    usage = TokenUsageSerializer(read_only=True)
    turns = ExplanationTurnSerializer(many=True, read_only=True)

    class Meta:
        model = Explanation
        fields = (
            "id",
            "kind",
            "subject",
            "period_start",
            "period_end",
            "prompt_version",
            "provider",
            "model",
            "effort",
            "content",
            "usage",
            "cost",
            "useful",
            "created",
            "turns",
        )

    def get_subject(self, explanation) -> int | None:
        return getattr(explanation, f"{explanation.kind}_id")


class ExplanationQuerySerializer(serializers.Serializer):
    hand = serializers.IntegerField(required=False)
    attempt = serializers.IntegerField(required=False)
    decision = serializers.IntegerField(required=False)
    debrief = serializers.IntegerField(required=False)
    test = serializers.IntegerField(required=False)
    session = serializers.IntegerField(required=False)

    def validate(self, data):
        if len(data) != 1:
            raise serializers.ValidationError("Give exactly one of hand, attempt, decision, debrief, test or session.")
        return data


class ExplanationUpdateSerializer(Strict):
    """The player's rating of an explanation."""

    useful = serializers.BooleanField(allow_null=True)


class ConversationMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLES)
    text = serializers.CharField()


class TurnBriefSerializer(serializers.Serializer):
    instructions = serializers.CharField(help_text="The system prompt for a question about the explanation.")
    messages = ConversationMessageSerializer(
        many=True, help_text="The conversation so far; the new question goes after it."
    )
    after = serializers.IntegerField(help_text="How many questions there are so far, sent back with the answer.")


class TurnCreateSerializer(WrittenSerializer):
    """A question about an explanation, and a model's answer to it."""

    after = serializers.IntegerField(min_value=0)
    question = serializers.CharField(max_length=QUESTION_LENGTH)
    answer = serializers.CharField(max_length=ANSWER_LENGTH)
