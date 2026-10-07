from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from hands.filters import PLAYED, SORT_ORDERS, UTC, narrow
from hands.models import Hand
from hands.serializers import (
    HandCalendarSerializer,
    HandDaysQuerySerializer,
    HandDetailSerializer,
    HandListQuerySerializer,
    HandSummarySerializer,
    HandTagSerializer,
    StatGroupSerializer,
    StatsQuerySerializer,
)
from hands.stats import hand_bb, hero_stats, played_days, streaks, tag_stats


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
        if by_result or any(filters.get(name) for name in ("tag", "date", "since", "until", "stat", "result")):
            # As the home page counts them.
            hands = hands.filter(PLAYED)
        hands = narrow(hands, filters)
        return hands.annotate(net_bb=hand_bb()) if by_result else hands


class HandDetailView(RetrieveAPIView):
    """One of the signed-in user's hands, with what its replay needs."""

    serializer_class = HandDetailSerializer

    def get_queryset(self):
        return Hand.objects.filter(user=self.request.user)


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
        calendar = {
            "days": [{"date": day["day"], "hands": day["hands"], "net_bb": round(day["net_bb"], 2)} for day in days],
            "current_streak": current_streak,
            "best_streak": best_streak,
            "played_today": bool(days) and days[-1]["day"] == today,
        }
        return Response(HandCalendarSerializer(calendar).data)


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
