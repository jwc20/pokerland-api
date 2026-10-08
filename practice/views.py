from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from hands.filters import PLAYED
from hands.models import Hand
from practice import book, debrief, matches, sets
from practice.models import Attempt, CoachedMatch, Playbook, Review, RuleProgress, ScenarioSet
from practice.playbook import FAMILIES
from practice.serializers import (
    ActRequestSerializer,
    AttemptRequestSerializer,
    AttemptResultSerializer,
    BookQuerySerializer,
    BookSerializer,
    DebriefSerializer,
    DepartureRequestSerializer,
    IntentRequestSerializer,
    MatchStartSerializer,
    MatchStateSerializer,
    MatchSummarySerializer,
    NewSetSerializer,
    NoteRequestSerializer,
    PlaybookDetailSerializer,
    PlaybookSerializer,
    PracticeProfileSerializer,
    PracticeSetSerializer,
    ReviewRequestSerializer,
    ReviewSerializer,
    TimeZoneQuerySerializer,
)


def set_data(practice_set):
    """A set with its spots in order, each with the last answer given to it in the set."""
    attempts = {}
    for attempt in Attempt.objects.filter(set=practice_set).select_related("scenario").order_by("created"):
        attempts[attempt.scenario_id] = attempt
    spots = [
        {
            "position": item.position,
            "review": item.review,
            "scenario": item.scenario,
            "attempt": attempts.get(item.scenario_id),
        }
        for item in practice_set.items.select_related("scenario")
    ]
    return {**{field: getattr(practice_set, field) for field in PracticeSetSerializer.Meta.fields[:-1]}, "spots": spots}


def today(request):
    query = TimeZoneQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    return timezone.localdate(timezone=query.validated_data["tz"])


class TodaySetView(APIView):
    """Today's set for the signed-in user, made the first time it is asked for: reviews due, spots from their own
    hands at least a day old, and generated spots to fill it."""

    @extend_schema(parameters=[TimeZoneQuerySerializer], responses=PracticeSetSerializer)
    def get(self, request):
        practice_set = sets.daily_set(request.user, today(request))
        return Response(PracticeSetSerializer(set_data(practice_set)).data)


class SetListView(APIView):
    """A new set of one mode: decisions from the user's own hands, or generated spots for one skill."""

    @extend_schema(request=NewSetSerializer, responses={status.HTTP_201_CREATED: PracticeSetSerializer})
    def post(self, request):
        query = NewSetSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        day = timezone.localdate(timezone=data["tz"])
        practice_set = sets.mode_set(request.user, data["kind"], day, data.get("skill", ""))
        return Response(PracticeSetSerializer(set_data(practice_set)).data, status=status.HTTP_201_CREATED)


class SetDetailView(APIView):
    """One of the signed-in user's sets, with the answers given so far."""

    @extend_schema(responses=PracticeSetSerializer)
    def get(self, request, pk):
        practice_set = get_object_or_404(ScenarioSet, pk=pk, user=request.user)
        return Response(PracticeSetSerializer(set_data(practice_set)).data)


class AttemptView(APIView):
    """Answers a spot: the grade, the answer and how it was worked out. A miss comes back tomorrow."""

    @extend_schema(request=AttemptRequestSerializer, responses={status.HTTP_201_CREATED: AttemptResultSerializer})
    def post(self, request):
        query = AttemptRequestSerializer(data=request.data, context={"request": request})
        query.is_valid(raise_exception=True)
        data = query.validated_data
        day = timezone.localdate(timezone=data["tz"])
        attempt = sets.record(request.user, data["scenario"], data.get("set"), data, day)
        return Response(AttemptResultSerializer(attempt).data, status=status.HTTP_201_CREATED)


class ReviewView(APIView):
    """"Again later": the spot comes back tomorrow, then further away each time it is answered well."""

    @extend_schema(request=ReviewRequestSerializer, responses={status.HTTP_201_CREATED: ReviewSerializer})
    def post(self, request):
        query = ReviewRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        scenario = query.validated_data["scenario"]
        if scenario.owner_id not in (None, request.user.pk):
            return Response({"scenario": ["Not found."]}, status=status.HTTP_400_BAD_REQUEST)
        sets.again_later(request.user, scenario, timezone.localdate(timezone=query.validated_data["tz"]))
        review = Review.objects.get(user=request.user, scenario=scenario)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class ProfileView(APIView):
    """The signed-in user's practice: each skill's accuracy with its 95% range, and the days they practised."""

    @extend_schema(parameters=[TimeZoneQuerySerializer], responses=PracticeProfileSerializer)
    def get(self, request):
        query = TimeZoneQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        tz = query.validated_data["tz"]
        calendar = sets.practice_days(request.user, tz)
        profile = {
            "skills": sets.skill_scores(request.user),
            **calendar,
            "reviews_due": Review.objects.filter(user=request.user, due__lte=calendar["today"]).count(),
            "generated": [{"skill": skill, "label": label} for skill, (label, _) in sets.GENERATED.items()],
        }
        return Response(PracticeProfileSerializer(profile).data)


def visible_playbooks(user):
    """The house presets, saved as they are first used, and the user's own playbooks."""
    sets.house_playbook()
    return Playbook.objects.filter(Q(owner=None) | Q(owner=user)).order_by("owner", "key", "-version")


def family_stages(user, playbook):
    """The user's stage in each of the playbook's rule families; stage 1 until a match moves it."""
    progress = {row.family: row for row in RuleProgress.objects.filter(user=user, playbook_key=playbook.key)}
    used = {rule["family"] for rule in playbook.rules}
    return [
        {
            "family": family,
            "label": label,
            "stage": progress[family].stage if family in progress else 1,
            "recent": progress[family].recent if family in progress else [],
        }
        for family, label in FAMILIES.items()
        if family in used
    ]


class PlaybookListView(APIView):
    """The playbooks the signed-in user can play by: the house presets and their own."""

    @extend_schema(responses=PlaybookSerializer(many=True))
    def get(self, request):
        return Response(PlaybookSerializer(visible_playbooks(request.user), many=True).data)


class PlaybookDetailView(APIView):
    """A playbook's rule cards, and the signed-in user's stage in each of its rule families."""

    @extend_schema(responses=PlaybookDetailSerializer)
    def get(self, request, pk):
        playbook = get_object_or_404(visible_playbooks(request.user), pk=pk)
        playbook.families = family_stages(request.user, playbook)
        return Response(PlaybookDetailSerializer(playbook).data)


class BookView(APIView):
    """By the book: how often the signed-in user's recent hands, at least a day old, kept each of a playbook's
    default rules; with `rule`, the decisions it applied to."""

    @extend_schema(parameters=[BookQuerySerializer], responses=BookSerializer)
    def get(self, request):
        query = BookQuerySerializer(data=request.query_params, context={"request": request})
        query.is_valid(raise_exception=True)
        playbook, rule = query.validated_data["playbook"], query.validated_data.get("rule")
        found = book.by_the_book(request.user, playbook.rules)
        counted = Hand.objects.filter(PLAYED, user=request.user, played_at__lt=timezone.now() - sets.MIN_AGE)
        data = {
            "hands": min(counted.count(), book.RECENT_HANDS),
            "rules": book.summarise(found),
        }
        if rule:
            data["chances"] = book.listed(found[rule])
        return Response(BookSerializer(data).data)


class MatchListView(APIView):
    """The signed-in user's coached matches, most recent first; and a new one."""

    @extend_schema(responses=MatchSummarySerializer(many=True))
    def get(self, request):
        recent = CoachedMatch.objects.filter(user=request.user).select_related("table")[:20]
        return Response(MatchSummarySerializer(recent, many=True).data)

    @extend_schema(request=MatchStartSerializer, responses={status.HTTP_201_CREATED: MatchStateSerializer})
    def post(self, request):
        query = MatchStartSerializer(data=request.data, context={"request": request})
        query.is_valid(raise_exception=True)
        data = query.validated_data
        playbook = data.get("playbook") or sets.house_playbook()
        match = matches.start(request.user, playbook, data["opponent"], data["coach"])
        return Response(MatchStateSerializer(matches.state(match)).data, status=status.HTTP_201_CREATED)


class MatchView(APIView):
    """A step in one of the signed-in user's matches. Every one answers with the match as it stands."""

    def match(self, request, pk):
        return get_object_or_404(CoachedMatch.objects.select_related("table", "playbook"), pk=pk, user=request.user)

    def respond(self, match):
        match.refresh_from_db()
        return Response(MatchStateSerializer(matches.state(match)).data)

    def run(self, step):
        try:
            return step()
        except matches.MatchError as error:
            raise ValidationError({"detail": str(error)}) from None


class MatchDetailView(MatchView):
    """The match as it stands: the hand, your moves, what the coach may say at this stage, and the read card."""

    @extend_schema(responses=MatchStateSerializer)
    def get(self, request, pk):
        return self.respond(self.match(request, pk))


class MatchActView(MatchView):
    """Your move. The bot answers, and the coach speaks as the stage allows."""

    @extend_schema(request=ActRequestSerializer, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        query = ActRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        move = (data["action"], data.get("amount"), data.get("time_taken"), data.get("reason"))
        self.run(lambda: matches.act(match, *move))
        return self.respond(match)


class MatchIntentView(MatchView):
    """Stage 2, "call it": what you would do and why. The coach's verdict comes back before you act."""

    @extend_schema(request=IntentRequestSerializer, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        query = IntentRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        self.run(lambda: matches.say_intent(match, data["action"], data.get("amount"), data["reason"]))
        return self.respond(match)


class MatchAskView(MatchView):
    """"Ask the coach" at stage 3 or 4: the advice now. Each use is counted."""

    @extend_schema(request=None, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        self.run(lambda: matches.ask_coach(match))
        return self.respond(match)


class MatchNextView(MatchView):
    """Deals the next hand once the last is over."""

    @extend_schema(request=None, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        self.run(lambda: matches.next_hand(match))
        return self.respond(match)


class MatchResignView(MatchView):
    """Ends the match early, as it stands, and opens the debrief."""

    @extend_schema(request=None, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        matches.resign(match)
        return self.respond(match)


class MatchDepartureView(MatchView):
    """Why you left a rule: a read, the price, the stack depth, or it felt right. Asked once."""

    @extend_schema(request=DepartureRequestSerializer, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        query = DepartureRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        self.run(lambda: matches.explain_departure(match, data["hand"], data["step"], data["why"]))
        return self.respond(match)


class MatchReadsView(MatchView):
    """Adds or revises a note on the read card: what a showdown told you, a read, or a label."""

    @extend_schema(request=NoteRequestSerializer, responses=MatchStateSerializer)
    def post(self, request, pk):
        match = self.match(request, pk)
        query = NoteRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        if data["kind"] == "read" and data["withdraw"]:
            matches.withdraw(match, data["tag"])
        else:
            matches.note(match, data["kind"], data["tag"], data.get("hand"))
        return self.respond(match)


class MatchDebriefView(MatchView):
    """The debrief, with the bot revealed, once the match is over."""

    @extend_schema(responses=DebriefSerializer)
    def get(self, request, pk):
        match = self.match(request, pk)
        if not match.finished:
            raise ValidationError({"detail": "The match isn't over."})
        return Response(DebriefSerializer(debrief.debrief(match)).data)
