import datetime
import hashlib
import json
import secrets
from collections import defaultdict

from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.generics import (
    DestroyAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from hands.cards import board_reader, equity, outs
from hands.filters import PLAYED, SORT_ORDERS, UTC, day_bounds, narrow
from hands.leaks import CHECKS, leak_hands, leaks, mark_reviewed, preset_rows, presets_of, save_presets
from hands.models import Hand, HandNote, HandShare, Opponent, SavedRange, Session, Spot, Tournament
from hands.notes import purpose_stats, review_summary, save_note
from hands.opponents import OPPONENT_SORTS, effective_label, ledger, showdowns
from hands.opponents import positions as opponent_positions
from hands.reports import lines, sizing
from hands.sessions import patterns
from hands.shares import anonymized, new_slug
from hands.spots import shareable, spot_fields, spot_filter
from hands.tournaments import summary as tournament_summary
from hands.tournaments import timeline
from hands.serializers import (
    BoardStreetSerializer,
    EquityRequestSerializer,
    EquityResultSerializer,
    HandCalendarSerializer,
    HandDaysQuerySerializer,
    HandDetailSerializer,
    HandFilterSerializer,
    HandListQuerySerializer,
    HandNoteSerializer,
    HandNoteWriteSerializer,
    HandShareSerializer,
    HandSummarySerializer,
    HandTagSerializer,
    LeakQuerySerializer,
    LeakReviewSerializer,
    LeakSerializer,
    LedgerSerializer,
    LinesReportSerializer,
    OpponentDetailSerializer,
    OpponentQuerySerializer,
    OpponentSerializer,
    OpponentUpdateSerializer,
    OutsDecisionSerializer,
    PresetSerializer,
    PresetsUpdateSerializer,
    PublicShareSerializer,
    PurposeStatSerializer,
    ReviewQueueSerializer,
    SavedRangeSerializer,
    SessionPatternsSerializer,
    SessionQuerySerializer,
    SessionSerializer,
    SharedSpotSerializer,
    OpponentShowdownSerializer,
    SizingReportSerializer,
    SpotCountRequestSerializer,
    SpotCountSerializer,
    SpotFieldSerializer,
    SpotImportSerializer,
    SavedSpotSerializer,
    StatDefinitionSerializer,
    StatGroupSerializer,
    StatsQuerySerializer,
    TournamentDetailSerializer,
    TournamentQuerySerializer,
    TournamentSerializer,
    TournamentTotalsSerializer,
    TournamentUpdateSerializer,
)
from hands.stats import hand_bb, hero_stats, played_days, streaks, tag_stats, with_hero_all_in
from tracker.parsing.facts import STATS


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
        query = HandListQuerySerializer(data=self.request.query_params, context={"user": self.request.user})
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        by_result = filters["sort"] in ("biggest_win", "biggest_loss")
        narrowing = ("tag", "date", "since", "until", "stat", "result", "review", "note_tag", "leak", "session")
        narrowing += ("spot", "spec", "opponent", "tournament")
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
    """One of the signed-in user's hands, with what its replay needs, its tournament and its opponents' profiles."""

    serializer_class = HandDetailSerializer

    def get_queryset(self):
        return with_hero_all_in(Hand.objects.filter(user=self.request.user))

    def get_object(self):
        hand = super().get_object()
        names = [player["name"] for player in hand.replay.get("players", []) if player["name"] != hand.hero]
        found = Opponent.objects.filter(user=hand.user_id, site=hand.site, name__in=names)
        hand.opponent_rows = [{"name": o.name, "id": o.pk, "label": effective_label(o)} for o in found]
        tournament = Tournament.objects.filter(user=hand.user_id, site=hand.site, tournament_id=hand.tournament_id)
        hand.tournament_pk = tournament.values_list("pk", flat=True).first() if hand.tournament_id else None
        return hand


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
        query = StatsQuerySerializer(data=request.query_params, context={"user": request.user})
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), filters)
        stats = hero_stats(hands, filters["group_by"], filters.get("tz", UTC), filters["limit"])
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
        query = HandFilterSerializer(data=request.query_params, context={"user": request.user})
        query.is_valid(raise_exception=True)
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), query.validated_data)
        return Response(PurposeStatSerializer(purpose_stats(request.user, hands), many=True).data)


class LeaksView(APIView):
    """The leak checks over the signed-in user's hands as the hero (B3, B5): how often they broke each rule of thumb,
    before the flop or after it."""

    @extend_schema(parameters=[LeakQuerySerializer], responses=LeakSerializer(many=True))
    def get(self, request):
        query = LeakQuerySerializer(data=request.query_params, context={"user": request.user})
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), filters)
        checks = leaks(request.user, hands, presets_of(request.user), filters.get("tz", UTC), filters["group"])
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
        query = HandFilterSerializer(data=request.query_params, context={"user": request.user})
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        hands = narrow(Hand.objects.filter(PLAYED, user=request.user), filters)
        return Response(SessionPatternsSerializer(patterns(hands, filters.get("tz", UTC))).data)


# Reports: bet sizing (B4), lines after the flop (B6), and the statistics' dictionary (E5).


class SizingReportView(APIView):
    """The signed-in user's bets and raises after the flop by street and size, split by how strong their hand was:
    what their sizes give away (B4)."""

    @extend_schema(parameters=[HandFilterSerializer], responses=SizingReportSerializer)
    def get(self, request):
        hands = filtered_hands(request)
        return Response(SizingReportSerializer(sizing(hands)).data)


class LinesReportView(APIView):
    """How the signed-in user played the flop, turn and river by their part before the flop and position, and by
    the board's texture; and their barrels after a called c-bet (B6)."""

    @extend_schema(parameters=[HandFilterSerializer], responses=LinesReportSerializer)
    def get(self, request):
        hands = filtered_hands(request)
        return Response(LinesReportSerializer(lines(hands)).data)


def filtered_hands(request):
    """The signed-in user's hands, narrowed by the request's HandFilterSerializer parameters."""
    query = HandFilterSerializer(data=request.query_params, context={"user": request.user})
    query.is_valid(raise_exception=True)
    return narrow(Hand.objects.filter(PLAYED, user=request.user), query.validated_data)


class StatDictionaryView(APIView):
    """Every statistic and exactly what it counts: did ÷ could, as PokerTracker defines them [MIT 2]."""

    @extend_schema(responses=StatDefinitionSerializer(many=True))
    def get(self, request):
        rows = [{"key": key, "definition": text} for key, text in STATS.items()]
        rows.append({"key": "aggression", "definition": AGGRESSION_DEFINITION})
        return Response(StatDefinitionSerializer(rows, many=True).data)


AGGRESSION_DEFINITION = "Bet or raised after the flop: (bets + raises) ÷ (bets + raises + calls + folds)."


# Spots (FND-3, B7) and saved ranges (FND-5).


class SpotListView(ListCreateAPIView):
    """The signed-in user's saved spots, and saving a new one."""

    serializer_class = SavedSpotSerializer
    pagination_class = None

    def get_queryset(self):
        return Spot.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SpotDetailView(RetrieveUpdateDestroyAPIView):
    """One of the signed-in user's spots: renaming it, changing its conditions, or deleting it."""

    serializer_class = SavedSpotSerializer
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return Spot.objects.filter(user=self.request.user)


class SpotFieldsView(APIView):
    """The conditions a spot can hold, with the parameters each takes and their choices."""

    @extend_schema(responses=SpotFieldSerializer(many=True))
    def get(self, request):
        return Response(SpotFieldSerializer(spot_fields(), many=True).data)


class SpotCountView(APIView):
    """How many of the signed-in user's hands a spec matches, for the spot builder's live count."""

    @extend_schema(request=SpotCountRequestSerializer, responses=SpotCountSerializer)
    def post(self, request):
        query = SpotCountRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        spec, tz = query.validated_data["spec"], query.validated_data.get("tz", UTC)
        hands = Hand.objects.filter(PLAYED, spot_filter(spec, request.user, tz), user=request.user)
        return Response(SpotCountSerializer({"hands": hands.count()}).data)


class SpotShareView(APIView):
    """Gives one of the signed-in user's spots a share code, if it has none, so others can import a copy."""

    @extend_schema(request=None, responses=SavedSpotSerializer)
    def post(self, request, pk):
        spot = get_object_or_404(Spot, pk=pk, user=request.user)
        if not spot.share_code:
            spot.share_code = share_code()
            spot.save(update_fields=["share_code", "updated"])
        return Response(SavedSpotSerializer(spot).data)


def share_code():
    while True:
        code = secrets.token_urlsafe(8)[:10]
        if not Spot.objects.filter(share_code=code).exists():
            return code


class SharedSpotView(APIView):
    """A spot someone shared, by its code: its name and conditions, without any that name a player."""

    @extend_schema(responses=SharedSpotSerializer)
    def get(self, request, code):
        spot = get_object_or_404(Spot, share_code=code)
        shared = {"name": spot.name, "spec": shareable(spot.spec) or {"all": []}, "code": code}
        return Response(SharedSpotSerializer(shared).data)


class SpotImportView(APIView):
    """Saves a copy of a shared spot among the signed-in user's own."""

    @extend_schema(request=SpotImportSerializer, responses={status.HTTP_201_CREATED: SavedSpotSerializer})
    def post(self, request):
        query = SpotImportSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        shared = get_object_or_404(Spot, share_code=query.validated_data["code"])
        spot = Spot.objects.create(user=request.user, name=shared.name, spec=shareable(shared.spec) or {"all": []})
        return Response(SavedSpotSerializer(spot).data, status=status.HTTP_201_CREATED)


class RangeListView(ListCreateAPIView):
    """The signed-in user's saved starting-hand ranges, and saving a new one."""

    serializer_class = SavedRangeSerializer
    pagination_class = None

    def get_queryset(self):
        return SavedRange.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class RangeDetailView(RetrieveUpdateDestroyAPIView):
    """One of the signed-in user's saved ranges."""

    serializer_class = SavedRangeSerializer
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return SavedRange.objects.filter(user=self.request.user)


class LeakReviewView(APIView):
    """Marks one of the leak checks reviewed: the hands that broke it so far stop counting as new (B5)."""

    @extend_schema(request=None, responses=LeakReviewSerializer)
    def post(self, request, key):
        if key not in CHECKS:
            return Response({"detail": "Not a leak check."}, status=status.HTTP_404_NOT_FOUND)
        review = mark_reviewed(request.user, key, timezone.now())
        return Response(LeakReviewSerializer(review).data)


# Opponents (FND-6, C1 and C2).


class OpponentPagination(CursorPagination):
    ordering = ("-hands", "name", "id")
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_ordering(self, request, queryset, view):
        return (*OPPONENT_SORTS[request.query_params.get("sort") or "hands"], "id")


@extend_schema_view(get=extend_schema(parameters=[OpponentQuerySerializer]))
class OpponentListView(ListAPIView):
    """The players the signed-in user has played with, by most hands together, net against them, or last seen."""

    serializer_class = OpponentSerializer
    pagination_class = OpponentPagination

    def get_queryset(self):
        query = OpponentQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        opponents = Opponent.objects.filter(user=self.request.user, hands__gte=filters["min_hands"])
        if "search" in filters:
            opponents = opponents.filter(name__icontains=filters["search"])
        if "label" in filters:
            label = filters["label"]
            opponents = opponents.filter(Q(manual_label=label) | Q(manual_label="", label=label))
        return opponents


class OpponentDetailView(APIView):
    """An opponent's profile (C1): every statistic with its sample, their label and how sure it is, and their play
    by position; and the user's own label and note on them."""

    def opponent(self, request, pk):
        return get_object_or_404(Opponent, pk=pk, user=request.user)

    def respond(self, opponent):
        opponent.position_rows = opponent_positions(opponent)
        return Response(OpponentDetailSerializer(opponent).data)

    @extend_schema(responses=OpponentDetailSerializer)
    def get(self, request, pk):
        return self.respond(self.opponent(request, pk))

    @extend_schema(request=OpponentUpdateSerializer, responses=OpponentDetailSerializer)
    def patch(self, request, pk):
        opponent = self.opponent(request, pk)
        update = OpponentUpdateSerializer(data=request.data)
        update.is_valid(raise_exception=True)
        for name, value in update.validated_data.items():
            setattr(opponent, name, value)
        opponent.save(update_fields=[*update.validated_data, "updated"])
        return self.respond(opponent)


class OpponentShowdownsView(APIView):
    """The hands in which an opponent's cards were shown, the most surprising first [JHU 4]."""

    @extend_schema(responses=OpponentShowdownSerializer(many=True))
    def get(self, request, pk):
        opponent = get_object_or_404(Opponent, pk=pk, user=request.user)
        return Response(OpponentShowdownSerializer(showdowns(opponent), many=True).data)


class OpponentLedgerView(APIView):
    """The signed-in user against an opponent (C2): their net in the hands both played, by pot size."""

    @extend_schema(responses=LedgerSerializer)
    def get(self, request, pk):
        opponent = get_object_or_404(Opponent, pk=pk, user=request.user)
        return Response(LedgerSerializer(ledger(opponent)).data)


# Tournaments (FND-8, D1 and D2).


class TournamentPagination(CursorPagination):
    ordering = ("-first_hand", "-id")
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


def tournaments_of(request, query_class=TournamentQuerySerializer):
    query = query_class(data=request.query_params)
    query.is_valid(raise_exception=True)
    filters = query.validated_data
    tz = filters.get("tz", UTC)
    tournaments = Tournament.objects.filter(user=request.user)
    if "since" in filters:
        tournaments = tournaments.filter(first_hand__gte=day_bounds(filters["since"], tz)[0])
    if "until" in filters:
        tournaments = tournaments.filter(first_hand__lt=day_bounds(filters["until"], tz)[1])
    return tournaments


@extend_schema_view(get=extend_schema(parameters=[TournamentQuerySerializer]))
class TournamentListView(ListAPIView):
    """The signed-in user's tournaments, the latest first, with what each returned (D1)."""

    serializer_class = TournamentSerializer
    pagination_class = TournamentPagination

    def get_queryset(self):
        return tournaments_of(self.request)


class TournamentSummaryView(APIView):
    """The signed-in user's tournament totals: ROI, in the money and finishes, apart by money, then by buy-in and
    format; and the fees paid (D1, F6)."""

    @extend_schema(parameters=[TournamentQuerySerializer], responses=TournamentTotalsSerializer(many=True))
    def get(self, request):
        return Response(TournamentTotalsSerializer(tournament_summary(tournaments_of(request)), many=True).data)


class TournamentDetailView(APIView):
    """One of the signed-in user's tournaments with the hero's stack, hand by hand (D2); and setting what the hands
    can't tell: the field size, the payouts, or a finish, prize or entries."""

    def tournament(self, request, pk):
        return get_object_or_404(Tournament, pk=pk, user=request.user)

    def respond(self, tournament):
        tournament.points = timeline(tournament)
        return Response(TournamentDetailSerializer(tournament).data)

    @extend_schema(responses=TournamentDetailSerializer)
    def get(self, request, pk):
        return self.respond(self.tournament(request, pk))

    @extend_schema(request=TournamentUpdateSerializer, responses=TournamentDetailSerializer)
    def patch(self, request, pk):
        tournament = self.tournament(request, pk)
        update = TournamentUpdateSerializer(data=request.data)
        update.is_valid(raise_exception=True)
        for name, value in update.validated_data.items():
            setattr(tournament, name, value)
        tournament.save(update_fields=list(update.validated_data))
        return self.respond(tournament)


# Reading the cards (A2, A3), and the equity calculator.


def replay_of(hand):
    """A stored hand as hands.cards reads it: its replay with its hero and game."""
    return {**hand.replay, "hero": hand.hero, "game": hand.game, "site": hand.site, "hand_id": hand.hand_id}


class HandOutsView(APIView):
    """The hero's outs at each of their decisions on the flop and turn, against the hands shown (A2)."""

    @extend_schema(responses=OutsDecisionSerializer(many=True))
    def get(self, request, pk):
        hand = get_object_or_404(Hand, pk=pk, user=request.user)
        return Response(OutsDecisionSerializer(outs(replay_of(hand)), many=True).data)


BOARD_READER_VERSION = 1


class HandBoardView(APIView):
    """The board read on each street (A3): what it allows, the nuts, and the hero's hand among every holding left.
    Worked out the first time it is asked for, then kept with the hand's facts."""

    @extend_schema(responses=BoardStreetSerializer(many=True))
    def get(self, request, pk):
        hand = get_object_or_404(Hand, pk=pk, user=request.user)
        cached = (hand.facts or {}).get("board_reader")
        if cached and cached.get("version") == BOARD_READER_VERSION:
            return Response(cached["streets"])
        streets = BoardStreetSerializer(board_reader(replay_of(hand)), many=True).data
        facts = {**(hand.facts or {}), "board_reader": {"version": BOARD_READER_VERSION, "streets": streets}}
        Hand.objects.filter(pk=hand.pk).update(facts=facts)
        return Response(streets)


class EquityToolView(APIView):
    """A hold'em hand's equity against another hand, a range or a kind of hand on the board: exact when the
    run-outs are few enough to count, sampled otherwise (FND-2). Answers are kept for a day by their question."""

    @extend_schema(request=EquityRequestSerializer, responses=EquityResultSerializer)
    def post(self, request):
        query = EquityRequestSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        asked = query.validated_data
        key = "equity:" + hashlib.sha256(json.dumps(asked, sort_keys=True).encode()).hexdigest()
        answer = cache.get(key)
        if answer is None:
            try:
                answer = equity(asked["hero"], asked["board"], asked["villain"], asked["dead"])
            except ValueError as error:
                return Response({"villain": [str(error)]}, status=status.HTTP_400_BAD_REQUEST)
            cache.set(key, answer, EQUITY_CACHE_SECONDS)
        return Response(EquityResultSerializer(answer).data)


EQUITY_CACHE_SECONDS = 24 * 60 * 60


# Write-ups and share links (E2).


class ShareListView(ListCreateAPIView):
    """The signed-in user's shared hands, and sharing one: a public, read-only link to its replay and write-up."""

    serializer_class = HandShareSerializer
    pagination_class = None

    def get_queryset(self):
        return HandShare.objects.filter(user=self.request.user)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "user": self.request.user}

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, slug=new_slug())


class ShareDetailView(RetrieveUpdateDestroyAPIView):
    """One of the signed-in user's shares: its write-up, whether it is anonymized, revoking it, or deleting it."""

    serializer_class = HandShareSerializer
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return HandShare.objects.filter(user=self.request.user)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "user": self.request.user}


class PublicShareView(APIView):
    """A shared hand, as anyone with its link sees it: no sign-in needed, at a limited rate."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_share"

    @extend_schema(responses=PublicShareSerializer)
    def get(self, request, slug):
        share = get_object_or_404(HandShare, slug=slug, revoked=False)
        hand = with_hero_all_in(Hand.objects.filter(pk=share.hand_id)).get()
        shown = anonymized(hand) if share.anonymize else hand
        data = {
            "slug": share.slug,
            "write_up": share.write_up,
            "anonymized": share.anonymize,
            "created": share.created,
            "hand": shown,
        }
        return Response(PublicShareSerializer(data).data)
