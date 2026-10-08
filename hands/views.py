import datetime
from collections import defaultdict

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.generics import DestroyAPIView, ListAPIView, RetrieveAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from hands.filters import PLAYED, SORT_ORDERS, UTC, day_bounds, narrow
from hands.leaks import leak_hands, leaks, preset_rows, presets_of, save_presets
from hands.models import Hand, HandNote, Session
from hands.notes import purpose_stats, review_summary, save_note
from hands.sessions import patterns
from hands.serializers import (
    HandCalendarSerializer,
    HandDaysQuerySerializer,
    HandDetailSerializer,
    HandFilterSerializer,
    HandListQuerySerializer,
    HandNoteSerializer,
    HandNoteWriteSerializer,
    HandSummarySerializer,
    HandTagSerializer,
    LeakQuerySerializer,
    LeakSerializer,
    PresetSerializer,
    PresetsUpdateSerializer,
    PurposeStatSerializer,
    ReviewQueueSerializer,
    SessionPatternsSerializer,
    SessionQuerySerializer,
    SessionSerializer,
    StatGroupSerializer,
    StatsQuerySerializer,
)
from hands.stats import hand_bb, hero_stats, played_days, streaks, tag_stats, with_hero_all_in


class HandPagination(CursorPagination):
    # A cursor, not page numbers: new hands arrive at the top while the user pages down.
    ordering = SORT_ORDERS["newest"]
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_ordering(self, request, queryset, view):
        # The view validated `sort` when it built the queryset.
        return SORT_ORDERS[request.query_params.get("sort") or "newest"]


@extend_schema_view(get=extend_schema(parameters=[HandListQuerySerializer]))
class HandListView(ListAPIView):
    """The signed-in user's hands, most recent first, or narrowed by tags, days, decisions or results, or sorted."""

    serializer_class = HandSummarySerializer
    pagination_class = HandPagination

    def get_queryset(self):
        hands = Hand.objects.filter(user=self.request.user).defer("replay", "facts")
        query = HandListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        by_result = filters["sort"] in ("biggest_win", "biggest_loss")
        narrowing = ("tag", "date", "since", "until", "stat", "result", "review", "note_tag", "leak", "session")
        if by_result or any(filters.get(name) for name in narrowing):
            # As the home page counts them.
            hands = hands.filter(PLAYED)
        hands = narrow(hands, filters)
        if "leak" in filters:
            user = self.request.user
            hands = hands.filter(leak_hands(user, filters["leak"], presets_of(user)))
        hands = with_hero_all_in(hands)
        return hands.annotate(net_bb=hand_bb()) if by_result else hands


class HandDetailView(RetrieveAPIView):
    """One of the signed-in user's hands, with what its replay needs."""

    serializer_class = HandDetailSerializer

    def get_queryset(self):
        return with_hero_all_in(Hand.objects.filter(user=self.request.user))


class HandDaysView(APIView):
    """The days the signed-in user played hands on, in their time zone, with each day's result."""

    @extend_schema(parameters=[HandDaysQuerySerializer], responses=HandCalendarSerializer)
    def get(self, request):
        query = HandDaysQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        tz = query.validated_data["tz"]
        days = list(played_days(Hand.objects.filter(PLAYED, user=request.user), tz))
        today = timezone.localdate(timezone=tz)
        current_streak, best_streak = streaks([day["day"] for day in days], today)
        sessions = sessions_by_day(request.user, tz)
        calendar = {
            "days": [
                {
                    "date": day["day"],
                    "hands": day["hands"],
                    "net_bb": round(day["net_bb"], 2),
                    "sessions": sessions.get(day["day"], []),
                }
                for day in days
            ],
            "current_streak": current_streak,
            "best_streak": best_streak,
            "played_today": bool(days) and days[-1]["day"] == today,
        }
        return Response(HandCalendarSerializer(calendar).data)


def sessions_by_day(user, tz):
    """The user's sessions on each day in `tz` they were played on, a session past midnight on both days."""
    by_day = defaultdict(list)
    for session in Session.objects.filter(user=user).order_by("start"):
        brief = {
            "id": session.pk,
            "start": session.start,
            "end": session.end,
            "hands": session.hands,
            "net_bb": round(session.net_bb, 2),
        }
        day, last = session.start.astimezone(tz).date(), session.end.astimezone(tz).date()
        while day <= last:
            by_day[day].append(brief)
            day += datetime.timedelta(days=1)
    return by_day


class HandTagsView(APIView):
    """The signed-in user's hands counted by position, game, cash-game stakes and format, with how they went."""

    @extend_schema(responses=HandTagSerializer(many=True))
    def get(self, request):
        tags = tag_stats(Hand.objects.filter(PLAYED, user=request.user))
        return Response(HandTagSerializer(tags, many=True).data)


class StatsView(APIView):
    """The signed-in user's statistics as the hero, over all their hands or a tag's or a stretch of days'."""

    @extend_schema(parameters=[StatsQuerySerializer], responses=StatGroupSerializer(many=True))
    def get(self, request):
        query = StatsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), filters)
        stats = hero_stats(hands, filters["group_by"], filters.get("tz", UTC))
        return Response(StatGroupSerializer(stats, many=True).data)


class HandNotesView(APIView):
    """What the signed-in user wrote on one of their hands, and adding to it or changing it."""

    def hand(self, request, pk):
        return get_object_or_404(Hand, pk=pk, user=request.user)

    @extend_schema(responses=HandNoteSerializer(many=True))
    def get(self, request, pk):
        notes = self.hand(request, pk).notes.order_by("kind", "street", "bet", "value")
        return Response(HandNoteSerializer(notes, many=True).data)

    @extend_schema(
        request=HandNoteWriteSerializer,
        responses={status.HTTP_200_OK: HandNoteSerializer, status.HTTP_201_CREATED: HandNoteSerializer},
    )
    def post(self, request, pk):
        """Adds a note, or changes the one it takes the place of: 201 when added, 200 when changed."""
        hand = self.hand(request, pk)
        write = HandNoteWriteSerializer(data=request.data, context={"hand": hand})
        write.is_valid(raise_exception=True)
        note, created = save_note(request.user, hand, write.validated_data)
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(HandNoteSerializer(note).data, status=code)


class HandNoteDetailView(DestroyAPIView):
    """Removes a note from one of the signed-in user's hands: a note, a tag, the review state or a purpose."""

    serializer_class = HandNoteSerializer
    lookup_url_kwarg = "note_id"

    def get_queryset(self):
        return HandNote.objects.filter(user=self.request.user, hand_id=self.kwargs["pk"])


class ReviewView(APIView):
    """The signed-in user's review queue: the hands they flagged to look at again, and their tags."""

    @extend_schema(responses=ReviewQueueSerializer)
    def get(self, request):
        return Response(ReviewQueueSerializer(review_summary(request.user)).data)


class PurposeStatsView(APIView):
    """How the signed-in user's bets and raises went, by the purpose they gave them and by street."""

    @extend_schema(parameters=[HandFilterSerializer], responses=PurposeStatSerializer(many=True))
    def get(self, request):
        query = HandFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), query.validated_data)
        return Response(PurposeStatSerializer(purpose_stats(request.user, hands), many=True).data)


class LeaksView(APIView):
    """The leak checks over the signed-in user's hands as the hero (B3): how often they broke each rule of thumb."""

    @extend_schema(parameters=[LeakQuerySerializer], responses=LeakSerializer(many=True))
    def get(self, request):
        query = LeakQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), filters)
        checks = leaks(request.user, hands, presets_of(request.user), filters.get("tz", UTC))
        checks = [check for check in checks if check["group"] == filters["group"]]
        return Response(LeakSerializer(checks, many=True).data)


class CoachPresetsView(APIView):
    """The signed-in user's thresholds for the leak checks: the course values unless they set their own."""

    @extend_schema(responses=PresetSerializer(many=True))
    def get(self, request):
        return Response(PresetSerializer(preset_rows(request.user), many=True).data)

    @extend_schema(request=PresetsUpdateSerializer, responses=PresetSerializer(many=True))
    def patch(self, request):
        update = PresetsUpdateSerializer(data=request.data, context={"user": request.user})
        update.is_valid(raise_exception=True)
        save_presets(request.user, update.validated_data)
        return Response(PresetSerializer(preset_rows(request.user), many=True).data)


class SessionPagination(CursorPagination):
    ordering = ("-start", "-id")
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 50


def sessions_of(user):
    """The user's sessions, with how many of their hands are flagged to review and how many have notes."""
    return Session.objects.filter(user=user).annotate(
        flagged=Count("hand_set__notes", filter=Q(hand_set__notes__kind="review", hand_set__notes__value="to_review")),
        noted=Count("hand_set", filter=Q(hand_set__notes__isnull=False), distinct=True),
    )


@extend_schema_view(get=extend_schema(parameters=[SessionQuerySerializer]))
class SessionListView(ListAPIView):
    """The signed-in user's sessions, the latest first: stretches of play with no gap of over half an hour (F1)."""

    serializer_class = SessionSerializer
    pagination_class = SessionPagination

    def get_queryset(self):
        query = SessionQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        tz = filters.get("tz", UTC)
        sessions = sessions_of(self.request.user)
        if "since" in filters:
            sessions = sessions.filter(start__gte=day_bounds(filters["since"], tz)[0])
        if "until" in filters:
            sessions = sessions.filter(start__lt=day_bounds(filters["until"], tz)[1])
        return sessions


class SessionDetailView(RetrieveAPIView):
    """One of the signed-in user's sessions."""

    serializer_class = SessionSerializer

    def get_queryset(self):
        return sessions_of(self.request.user)


class SessionPatternsView(APIView):
    """The signed-in user's results by hour into the session, time of day, day of the week and tables at once."""

    @extend_schema(parameters=[HandFilterSerializer], responses=SessionPatternsSerializer)
    def get(self, request):
        query = HandFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), filters)
        return Response(SessionPatternsSerializer(patterns(hands, filters.get("tz", UTC))).data)
