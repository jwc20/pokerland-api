from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from practice import aptitude, book, coaching, debrief, matches, play, sets, shared, theirs
from practice.models import Attempt, CoachedMatch, Playbook, PracticeTable, Review, ScenarioSet
from practice.playbook import ACTIONS, CONDITIONS, FAMILIES, READS, PlaybookError
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
    PlaybookCopySerializer,
    PlaybookDetailSerializer,
    PlaybookSerializer,
    PlaybookVersionSerializer,
    PlaybookVocabularySerializer,
    PlayTableSerializer,
    PlayTableSummarySerializer,
    PracticeProfileSerializer,
    PracticeSetSerializer,
    ReviewRequestSerializer,
    ReviewSerializer,
    TableMoveSerializer,
    TableStartSerializer,
    TestAnswerSerializer,
    TestReportSerializer,
    TestStateSerializer,
    TestSummarySerializer,
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
    """A new set of one mode: decisions from the user's own hands, generated spots for one skill, the library, the
    user's opponents' decisions from their seat, or decisions in hands shared with their classes."""

    @extend_schema(request=NewSetSerializer, responses={status.HTTP_201_CREATED: PracticeSetSerializer})
    def post(self, request):
        query = NewSetSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        day = timezone.localdate(timezone=data["tz"])
        if data["kind"] == "their_seat":
            practice_set = theirs.their_set(request.user, day)
        elif data["kind"] == "shared":
            practice_set = shared.shared_set(request.user, day)
        else:
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
        if not shared.open_to(request.user, scenario):
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


class PlaybookListView(APIView):
    """The playbooks the signed-in user can play by: the house presets, their own and their classes'; and a new one of
    their own, a copy of one of those, to edit."""

    @extend_schema(responses=PlaybookSerializer(many=True))
    def get(self, request):
        playbooks = coaching.visible(request.user)
        context = {"request": request, "classes": coaching.classes_by_playbook(request.user)}
        return Response(PlaybookSerializer(playbooks, many=True, context=context).data)

    @extend_schema(request=PlaybookCopySerializer, responses={status.HTTP_201_CREATED: PlaybookDetailSerializer})
    def post(self, request):
        query = PlaybookCopySerializer(data=request.data, context={"request": request})
        query.is_valid(raise_exception=True)
        playbook = coaching.copy(request.user, query.validated_data["copy_of"], query.validated_data["name"])
        return Response(playbook_detail(request, playbook), status=status.HTTP_201_CREATED)


def playbook_detail(request, playbook):
    playbook.families = coaching.stages(request.user, playbook)
    return PlaybookDetailSerializer(playbook, context={"request": request}).data


class PlaybookDetailView(APIView):
    """A playbook's rule cards, and the signed-in user's stage in each of its rule families; for one of their own, its
    next version, or putting it away."""

    def playbook(self, request, pk, own=False):
        playbook = get_object_or_404(Playbook, pk=pk)
        allowed = playbook.owner_id == request.user.pk if own else coaching.can_read(request.user, playbook)
        if not allowed:
            raise Http404
        return playbook

    @extend_schema(responses=PlaybookDetailSerializer)
    def get(self, request, pk):
        return Response(playbook_detail(request, self.playbook(request, pk)))

    @extend_schema(request=PlaybookVersionSerializer, responses=PlaybookDetailSerializer)
    def put(self, request, pk):
        playbook = self.playbook(request, pk, own=True)
        query = PlaybookVersionSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            version = coaching.save_version(playbook, data["name"], data["description"], data["rules"])
        except PlaybookError as error:
            raise ValidationError({"rules": error.errors}) from None
        except ValueError as error:
            raise ValidationError({"detail": str(error)}) from None
        return Response(playbook_detail(request, version))

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def delete(self, request, pk):
        coaching.archive(self.playbook(request, pk, own=True))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlaybookVocabularyView(APIView):
    """What a coach's cards can say: every test the rule engine runs, with its kind of value, and the families,
    scopes, reads, actions and exceptions it knows."""

    @extend_schema(responses=PlaybookVocabularySerializer)
    def get(self, request):
        conditions = []
        for key, (kind, allowed, label) in CONDITIONS.items():
            entry = {"key": key, "kind": kind, "label": label}
            if kind == "choice":
                entry["choices"] = allowed
            elif kind == "number":
                entry["low"], entry["high"] = allowed
            conditions.append(entry)
        data = {
            "conditions": conditions,
            "families": [{"key": key, "label": label} for key, label in FAMILIES.items()],
            "scopes": [{"key": "anyone", "label": "Anyone"}, {"key": "heads_up", "label": "Heads-up"}]
            + [{"key": key, "label": label} for key, label in READS.items()],
            "reads": [{"key": key, "label": label} for key, label in READS.items()],
            "actions": list(ACTIONS),
            "unless": [
                {"key": "multiway", "label": "More than one opponent"},
                {"key": "short", "label": "10 bb or less"},
            ],
        }
        return Response(PlaybookVocabularySerializer(data).data)


class BookView(APIView):
    """By the book: how often the signed-in user's recent hands, at least a day old, kept each of a playbook's
    default rules; with `rule`, the decisions it applied to."""

    @extend_schema(parameters=[BookQuerySerializer], responses=BookSerializer)
    def get(self, request):
        query = BookQuerySerializer(data=request.query_params, context={"request": request})
        query.is_valid(raise_exception=True)
        playbook, rule = query.validated_data["playbook"], query.validated_data.get("rule")
        return Response(BookSerializer(book.report(request.user, playbook, rule)).data)


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


# The aptitude test -------------------------------------------------------------------------------------------------


def test_state(test):
    """A test as it goes, with the spot it asks now, chosen if need be."""
    item = aptitude.next_spot(test)
    test.refresh_from_db()
    return {
        "id": test.pk,
        "planned": test.planned,
        "answered": aptitude.answered(test),
        "created": test.created,
        "finished": test.finished,
        "spot": {"position": item.position, "scenario": item.scenario} if item else None,
    }


class TestListView(APIView):
    """The signed-in user's aptitude tests, the latest first; and a new one: 24 graded spots, about 12 minutes."""

    @extend_schema(responses=TestSummarySerializer(many=True))
    def get(self, request):
        tests = (
            ScenarioSet.objects.filter(user=request.user, kind="test")
            .annotate(answered=Count("attempts"))
            .order_by("-created")[:20]
        )
        return Response(TestSummarySerializer(tests, many=True).data)

    @extend_schema(request=TimeZoneQuerySerializer, responses={status.HTTP_201_CREATED: TestStateSerializer})
    def post(self, request):
        query = TimeZoneQuerySerializer(data=request.data)
        query.is_valid(raise_exception=True)
        test = aptitude.start(request.user, timezone.localdate(timezone=query.validated_data["tz"]))
        return Response(TestStateSerializer(test_state(test)).data, status=status.HTTP_201_CREATED)


class TestView(APIView):
    def test(self, request, pk):
        return get_object_or_404(ScenarioSet, pk=pk, user=request.user, kind="test")


class TestNextView(TestView):
    """The spot a test asks now, without its answer; none once the test is over."""

    @extend_schema(responses=TestStateSerializer)
    def get(self, request, pk):
        return Response(TestStateSerializer(test_state(self.test(request, pk))).data)


class TestAnswerView(TestView):
    """Answers the spot a test is asking. Nothing about the answer comes back until the test is over: only the next
    spot."""

    @extend_schema(request=TestAnswerSerializer, responses=TestStateSerializer)
    def post(self, request, pk):
        test = self.test(request, pk)
        query = TestAnswerSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            aptitude.answer(test, data["scenario"], data, timezone.localdate(timezone=data["tz"]))
        except aptitude.TestError as error:
            raise ValidationError({"scenario": [str(error)]}) from None
        return Response(TestStateSerializer(test_state(test)).data)


class TestEndView(TestView):
    """Ends a test early: the report covers the spots answered."""

    @extend_schema(request=None, responses=TestStateSerializer)
    def post(self, request, pk):
        test = self.test(request, pk)
        aptitude.give_up(test)
        return Response(TestStateSerializer(test_state(test)).data)


class TestDetailView(TestView):
    """A test's report, once it is over: accuracy and rating by skill, every spot with its answer, strengths and gaps
    in words, and what to practise next."""

    @extend_schema(responses=TestReportSerializer)
    def get(self, request, pk):
        test = self.test(request, pk)
        if not test.finished:
            raise ValidationError({"detail": "The test isn't over."})
        return Response(TestReportSerializer(aptitude.report(test)).data)


# Play it out -------------------------------------------------------------------------------------------------------


class TableListView(APIView):
    """The signed-in user's Play it out tables, the latest first; and a new one, from a deal or from a spot."""

    @extend_schema(responses=PlayTableSummarySerializer(many=True))
    def get(self, request):
        return Response(PlayTableSummarySerializer(play.recent(request.user), many=True).data)

    @extend_schema(request=TableStartSerializer, responses={status.HTTP_201_CREATED: PlayTableSerializer})
    def post(self, request):
        query = TableStartSerializer(data=request.data, context={"request": request})
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            if data.get("scenario"):
                table = play.start_spot(request.user, data["scenario"])
            else:
                table = play.start_deal(request.user, data["seats"], data["opponents"], data["stack_bb"])
        except play.PlayError as error:
            raise ValidationError({"detail": str(error)}) from None
        return Response(PlayTableSerializer(play.state(table)).data, status=status.HTTP_201_CREATED)


class TableView(APIView):
    def table(self, request, pk):
        return get_object_or_404(PracticeTable, pk=pk, user=request.user, kind="play")

    def run(self, table, step):
        try:
            step()
        except play.PlayError as error:
            raise ValidationError({"detail": str(error)}) from None
        table.refresh_from_db()
        return Response(PlayTableSerializer(play.state(table)).data)


class TableDetailView(TableView):
    """A Play it out table as it stands."""

    @extend_schema(responses=PlayTableSerializer)
    def get(self, request, pk):
        return Response(PlayTableSerializer(play.state(self.table(request, pk))).data)


class TableActView(TableView):
    """Your move; the bots answer, until it is your turn again or the hand is over."""

    @extend_schema(request=TableMoveSerializer, responses=PlayTableSerializer)
    def post(self, request, pk):
        table = self.table(request, pk)
        query = TableMoveSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        return self.run(table, lambda: play.act(table, data["action"], data.get("amount")))


class TableNextView(TableView):
    """Deals the next hand once the last is over; a busted stack buys in again."""

    @extend_schema(request=None, responses=PlayTableSerializer)
    def post(self, request, pk):
        table = self.table(request, pk)
        return self.run(table, lambda: play.next_hand(table))
