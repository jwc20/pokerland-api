"""Explanations (pokerland-llm-reports.md): the brief for a subject, and saving what a model wrote about it.

The player's browser calls the model with their own key. No endpoint here takes a key, and the request bodies refuse
fields they don't know (explain.checks.Strict), so one sent by mistake is turned away, not stored.
"""

import datetime
import zoneinfo

from django.conf import settings
from django.db.models import Count, Prefetch, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from explain import catalog
from explain.briefs import NotYet, as_json, build, followup_instructions
from explain.checks import ExplanationContentSerializer, scrub
from explain.kinds import KINDS
from explain.models import Explanation, ExplanationTurn
from explain.serializers import (
    BriefRequestSerializer,
    BriefSerializer,
    CatalogSerializer,
    ExplanationCreateSerializer,
    ExplanationQuerySerializer,
    ExplanationSerializer,
    ExplanationUpdateSerializer,
    SpendQuerySerializer,
    SpendSerializer,
    TurnBriefSerializer,
    TurnCreateSerializer,
    ExplanationTurnSerializer,
)

# Starting caps (pokerland-llm-reports.md, 5.5): the player's key pays the provider, but the rows are Pokerland's.
DAILY_EXPLANATIONS = 50
DAILY_QUESTIONS = 200
QUESTIONS_PER_EXPLANATION = 10
DAY = datetime.timedelta(days=1)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Not now."
    default_code = "conflict"


class ExplainView(APIView):
    """An explanations endpoint: 404 for everyone while explanations are off (settings.EXPLANATIONS_ENABLED)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.EXPLANATIONS_ENABLED:
            raise NotFound("Explanations aren't open.")


def subject_of(request, kind, pk):
    """The user's subject of a kind, once it's time to explain it: 404 if it isn't theirs, 409 if it's too soon."""
    spec = KINDS.get(kind)
    if spec is None:
        raise ValidationError({"kind": [f"{kind} can't be explained yet."]})
    subject = spec.load(request.user, pk)
    try:
        spec.ready(request.user, subject)
    except NotYet as reason:
        raise Conflict(str(reason)) from None
    return spec, subject


def explanations_of(user):
    return Explanation.objects.filter(user=user).prefetch_related(
        Prefetch("turns", queryset=ExplanationTurn.objects.order_by("created", "id"))
    )


class CatalogView(ExplainView):
    """The providers and models explanations can be written with, and about what each costs (explain.catalog)."""

    @extend_schema(responses=CatalogSerializer)
    def get(self, request):
        return Response(CatalogSerializer(catalog.listing(timezone.now())).data)


class SpendView(ExplainView):
    """How many explanations and questions the signed-in user saved this month, and about what they cost."""

    @extend_schema(parameters=[SpendQuerySerializer], responses=SpendSerializer)
    def get(self, request):
        query = SpendQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            tz = zoneinfo.ZoneInfo(query.validated_data.get("tz") or "UTC")
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"tz": ["Not a time zone."]}) from None
        now = timezone.now().astimezone(tz)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        made = Explanation.objects.filter(user=request.user, created__gte=start).aggregate(
            count=Count("id"), cost=Sum("cost")
        )
        asked = ExplanationTurn.objects.filter(explanation__user=request.user, created__gte=start).aggregate(
            count=Count("id"), cost=Sum("cost")
        )
        data = {
            "month": f"{now:%Y-%m}",
            "explanations": made["count"],
            "questions": asked["count"],
            "cost": (made["cost"] or 0) + (asked["cost"] or 0),
        }
        return Response(SpendSerializer(data).data)


class BriefView(ExplainView):
    """What to tell a model about one of the signed-in user's subjects, for a provider: the instructions, the
    subject as JSON, the schema the answer must match, and a hash to send back with it. 409 until it's time."""

    @extend_schema(request=BriefRequestSerializer, responses=BriefSerializer)
    def post(self, request):
        query = BriefRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        _, subject = subject_of(request, data["kind"], data["id"])
        brief = build(data["kind"], subject, data["provider"])
        return Response(BriefSerializer(brief_data(brief)).data)


def brief_data(brief):
    return {
        "kind": brief.kind,
        "id": brief.subject_id,
        "provider": brief.provider,
        "prompt_version": brief.prompt_version,
        "instructions": brief.instructions,
        "input": brief.input,
        "schema": brief.schema,
        "hash": brief.hash,
    }


class ExplanationListView(ExplainView):
    """The explanations of one of the signed-in user's subjects, newest first; and saving a new one."""

    @extend_schema(parameters=[ExplanationQuerySerializer], responses=ExplanationSerializer(many=True))
    def get(self, request):
        query = ExplanationQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        ((kind, pk),) = query.validated_data.items()
        found = explanations_of(request.user).filter(kind=kind, **{f"{kind}_id": pk})
        return Response(ExplanationSerializer(found, many=True).data)

    @extend_schema(request=ExplanationCreateSerializer, responses={status.HTTP_201_CREATED: ExplanationSerializer})
    def post(self, request):
        """Saves what a model wrote about a subject, once it passes explain.checks: 400 with what failed, 409 if the
        subject changed while the model was writing."""
        write = ExplanationCreateSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        data = write.validated_data
        spec, subject = subject_of(request, data["kind"], data["id"])
        now = timezone.now()
        if Explanation.objects.filter(user=request.user, created__gte=now - DAY).count() >= DAILY_EXPLANATIONS:
            raise Throttled(detail=f"That's {DAILY_EXPLANATIONS} explanations in a day. Try again tomorrow.")
        brief = build(data["kind"], subject, data["provider"])
        if brief.hash != data["brief_hash"]:
            raise Conflict("This changed while the model was writing. Explain it again.")
        content = ExplanationContentSerializer(data=data["content"], context={"brief": brief})
        if not content.is_valid():
            raise ValidationError({"content": content.errors})
        period = {}
        if data["kind"] == "session":
            period = {"period_start": subject.start, "period_end": subject.end}
        explanation = Explanation.objects.create(
            user=request.user,
            kind=data["kind"],
            **{spec.field: subject},
            **period,
            prompt_version=brief.prompt_version,
            brief_hash=brief.hash,
            provider=data["provider"],
            model=data["model"],
            effort=data["effort"],
            content=content.validated_data,
            usage=data["usage"],
            cost=catalog.cost(data["provider"], data["model"], data["usage"], now),
            request_id=data["request_id"],
        )
        saved = explanations_of(request.user).get(pk=explanation.pk)
        return Response(ExplanationSerializer(saved).data, status=status.HTTP_201_CREATED)


class ExplanationDetailView(ExplainView):
    """One of the signed-in user's explanations: rating it as useful or not, or deleting it."""

    def explanation(self, request, pk):
        return get_object_or_404(explanations_of(request.user), pk=pk)

    @extend_schema(request=ExplanationUpdateSerializer, responses=ExplanationSerializer)
    def patch(self, request, pk):
        explanation = self.explanation(request, pk)
        update = ExplanationUpdateSerializer(data=request.data)
        update.is_valid(raise_exception=True)
        explanation.useful = update.validated_data["useful"]
        explanation.save(update_fields=["useful"])
        return Response(ExplanationSerializer(explanation).data)

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def delete(self, request, pk):
        self.explanation(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def conversation(request, pk):
    """One of the user's explanations and the brief it was written from, rebuilt: 409 if its subject has changed
    since (or a new prompt version has), since the questions would be about something else. The brief is rebuilt
    for the provider that wrote the explanation, whose hash it kept; its input is the same for every provider."""
    explanation = get_object_or_404(explanations_of(request.user), pk=pk)
    subject_id = getattr(explanation, f"{KINDS[explanation.kind].field}_id")
    if subject_id is None:
        raise Conflict("What this explained has been rebuilt since. Explain it again.")
    _, subject = subject_of(request, explanation.kind, subject_id)
    brief = build(explanation.kind, subject, explanation.provider)
    if brief.hash != explanation.brief_hash:
        raise Conflict("This has changed since it was explained. Explain it again.")
    return explanation, brief


class TurnBriefView(ExplainView):
    """The conversation so far about one of the signed-in user's explanations, for a model to answer a question."""

    @extend_schema(responses=TurnBriefSerializer)
    def get(self, request, pk):
        explanation, brief = conversation(request, pk)
        messages = [
            {"role": "user", "text": brief.input},
            {"role": "assistant", "text": as_json(explanation.content)},
        ]
        for turn in explanation.turns.all():
            messages += [{"role": "user", "text": turn.question}, {"role": "assistant", "text": turn.answer}]
        data = {
            "instructions": followup_instructions(explanation.kind),
            "messages": messages,
            "after": len(explanation.turns.all()),
        }
        return Response(TurnBriefSerializer(data).data)


class TurnListView(ExplainView):
    """Saving a question about one of the signed-in user's explanations, and the answer a model gave it."""

    @extend_schema(request=TurnCreateSerializer, responses={status.HTTP_201_CREATED: ExplanationTurnSerializer})
    def post(self, request, pk):
        write = TurnCreateSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        data = write.validated_data
        explanation, _ = conversation(request, pk)
        asked = len(explanation.turns.all())
        if data["after"] != asked:
            raise Conflict("Another question was answered meanwhile. Ask again.")
        if asked >= QUESTIONS_PER_EXPLANATION:
            raise Throttled(detail=f"That's {QUESTIONS_PER_EXPLANATION} questions on one explanation.")
        now = timezone.now()
        today = ExplanationTurn.objects.filter(explanation__user=request.user, created__gte=now - DAY).count()
        if today >= DAILY_QUESTIONS:
            raise Throttled(detail=f"That's {DAILY_QUESTIONS} questions in a day. Try again tomorrow.")
        turn = ExplanationTurn.objects.create(
            explanation=explanation,
            question=scrub(data["question"]),
            answer=scrub(data["answer"]),
            provider=data["provider"],
            model=data["model"],
            usage=data["usage"],
            cost=catalog.cost(data["provider"], data["model"], data["usage"], now),
            request_id=data["request_id"],
        )
        return Response(ExplanationTurnSerializer(turn).data, status=status.HTTP_201_CREATED)
