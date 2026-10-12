"""Checks on what a model wrote, before it's saved (pokerland-llm-reports.md, 5.5).

The player's browser posts the answer, so the API checks it against the brief rebuilt here: the shape and the lengths
(explain.schema leaves lengths to the instructions, since not every provider takes them in a schema), one entry for
each decision in the brief with the brief's own verdict, and a "Practise it" link from the brief's list. Anything
shaped like an API key is replaced before anything is saved, in case a player pastes theirs into a question.

Request bodies are strict: an unexpected field is an error naming the field, never echoing its value, so a client
that put a key where it doesn't belong fails loudly instead of having it dropped or stored.
"""

import re
from collections.abc import Mapping

from rest_framework import serializers

from explain.schema import PRIORITIES, VERDICTS

# Anthropic's, OpenAI's and DeepSeek's keys start "sk-"; Google's "AIza".
KEY_SHAPES = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}|\bAIza[0-9A-Za-z_-]{30,}")
REMOVED = "[key removed]"

QUESTION_LENGTH = 1000
ANSWER_LENGTH = 8000


def scrub(value):
    """`value`, with anything shaped like an API key in its text replaced."""
    if isinstance(value, str):
        return KEY_SHAPES.sub(REMOVED, value)
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    return value


class Strict(serializers.Serializer):
    """A request body that refuses fields it doesn't know, naming them without their values."""

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise serializers.ValidationError({name: ["Unexpected field."] for name in unknown})
        return super().to_internal_value(data)


class ExplanationStorySerializer(serializers.Serializer):
    label = serializers.CharField(max_length=40)
    text = serializers.CharField(max_length=1200)


class ExplanationDecisionSerializer(serializers.Serializer):
    ref = serializers.CharField(max_length=8)
    verdict = serializers.ChoiceField(choices=VERDICTS)
    why = serializers.CharField(max_length=1200)
    instead = serializers.CharField(max_length=1200, allow_null=True, allow_blank=True, required=False, default=None)
    # Where the decision was, from the brief, not the model: kept beside its words for the page to link to.
    step = serializers.IntegerField(read_only=True, allow_null=True, help_text="Its step in the replay, for a hand.")
    street = serializers.CharField(read_only=True, allow_null=True)
    move = serializers.CharField(read_only=True, allow_null=True, help_text="What the player did, in words.")
    rule = serializers.IntegerField(read_only=True, allow_null=True, help_text="The playbook rule's number, if any.")

    def to_internal_value(self, data):
        # Structured output can capitalise an enum value; the verdict is compared ignoring case.
        if isinstance(data, Mapping) and isinstance(data.get("verdict"), str):
            data = {**data, "verdict": data["verdict"].strip().lower()}
        return super().to_internal_value(data)


class ExplanationSuggestionSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=PRIORITIES)
    text = serializers.CharField(max_length=600)
    practice = serializers.CharField(max_length=64, allow_null=True, allow_blank=True, required=False, default=None)

    def to_internal_value(self, data):
        if isinstance(data, Mapping) and isinstance(data.get("priority"), str):
            data = {**data, "priority": data["priority"].strip().lower()}
        return super().to_internal_value(data)


class ExplanationContentSerializer(serializers.Serializer):
    """An explanation as explain.schema shapes it, with the lengths the instructions ask for (and some room)."""

    headline = serializers.CharField(max_length=160)
    summary = serializers.CharField(max_length=1200)
    story = ExplanationStorySerializer(many=True, max_length=8)
    decisions = ExplanationDecisionSerializer(many=True, max_length=24)
    strengths = serializers.ListField(child=serializers.CharField(max_length=400), max_length=4)
    suggestions = ExplanationSuggestionSerializer(many=True, min_length=1, max_length=4)
    luck = serializers.CharField(max_length=1200, allow_null=True, allow_blank=True, required=False, default=None)
    caveats = serializers.ListField(child=serializers.CharField(max_length=400), max_length=6)

    def validate(self, data):
        """The decisions are the brief's, each with the brief's verdict, put in the brief's order; every suggestion's
        *Practise it* is one of the brief's links; empty optional texts are nulls; and no key-shaped text survives."""
        brief = self.context["brief"]
        found = {}
        for decision in data["decisions"]:
            ref = decision["ref"]
            if ref not in brief.decisions:
                raise serializers.ValidationError({"decisions": [f"There's no decision {ref} in the brief."]})
            if ref in found:
                raise serializers.ValidationError({"decisions": [f"Decision {ref} is there twice."]})
            wanted = brief.decisions[ref]["verdict"]
            if decision["verdict"] != wanted:
                raise serializers.ValidationError(
                    {"decisions": [f"Decision {ref} has the verdict {decision['verdict']}; the brief's is {wanted}."]}
                )
            where = {key: brief.decisions[ref].get(key) for key in ("step", "street", "move", "rule")}
            found[ref] = {**decision, "instead": decision.get("instead") or None, **where}
        missing = [ref for ref in brief.decisions if ref not in found]
        if missing:
            raise serializers.ValidationError({"decisions": [f"Missing decisions: {', '.join(missing)}."]})
        suggestions = []
        for suggestion in data["suggestions"]:
            practice = suggestion.get("practice") or None
            if practice is not None and practice not in brief.links:
                raise serializers.ValidationError({"suggestions": [f"{practice} isn't one of the brief's links."]})
            suggestions.append({**suggestion, "practice": practice})
        content = {
            "headline": data["headline"],
            "summary": data["summary"],
            "story": data["story"],
            "decisions": [found[ref] for ref in brief.decisions],
            "strengths": data["strengths"],
            "suggestions": suggestions,
            "luck": data.get("luck") or None,
            "caveats": data["caveats"],
        }
        return scrub(content)
