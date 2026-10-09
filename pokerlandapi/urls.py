from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from hands.views import (
    CoachPresetsView,
    EquityToolView,
    LeakReviewView,
    LeaksView,
    LinesReportView,
    OpponentDetailView,
    OpponentLedgerView,
    OpponentListView,
    OpponentShowdownsView,
    PublicShareView,
    PurposeStatsView,
    RangeDetailView,
    RangeListView,
    ReviewView,
    SessionDetailView,
    SessionListView,
    SessionPatternsView,
    ShareDetailView,
    SharedSpotView,
    ShareListView,
    SizingReportView,
    SpotCountView,
    SpotDetailView,
    SpotFieldsView,
    SpotImportView,
    SpotListView,
    SpotShareView,
    StatDictionaryView,
    StatsView,
    TournamentDetailView,
    TournamentListView,
    TournamentSummaryView,
)
from pokerlandapi import schema  # noqa: F401  registers the OpenAPI extensions
from pokerlandapi.views import RegisterView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("dj_rest_auth.urls")),
    # Listed before the include so it replaces dj-rest-auth's RegisterView.
    path("api/auth/registration/", RegisterView.as_view(), name="rest_register"),
    path("api/auth/registration/", include("dj_rest_auth.registration.urls")),
    path("api/users/", include("users.urls")),
    path("api/tracker/", include("tracker.urls")),
    path("api/hands/", include("hands.urls")),
    path("api/stats/", StatsView.as_view(), name="stats"),
    path("api/stats/purposes/", PurposeStatsView.as_view(), name="purpose-stats"),
    path("api/stats/sizing/", SizingReportView.as_view(), name="sizing-report"),
    path("api/stats/lines/", LinesReportView.as_view(), name="lines-report"),
    path("api/stats/dictionary/", StatDictionaryView.as_view(), name="stat-dictionary"),
    path("api/review/", ReviewView.as_view(), name="review"),
    path("api/leaks/", LeaksView.as_view(), name="leaks"),
    path("api/leaks/presets/", CoachPresetsView.as_view(), name="coach-presets"),
    path("api/leaks/<str:key>/reviewed/", LeakReviewView.as_view(), name="leak-reviewed"),
    path("api/sessions/", SessionListView.as_view(), name="session-list"),
    path("api/sessions/patterns/", SessionPatternsView.as_view(), name="session-patterns"),
    path("api/sessions/<int:pk>/", SessionDetailView.as_view(), name="session-detail"),
    path("api/spots/", SpotListView.as_view(), name="spot-list"),
    path("api/spots/fields/", SpotFieldsView.as_view(), name="spot-fields"),
    path("api/spots/count/", SpotCountView.as_view(), name="spot-count"),
    path("api/spots/import/", SpotImportView.as_view(), name="spot-import"),
    path("api/spots/shared/<str:code>/", SharedSpotView.as_view(), name="spot-shared"),
    path("api/spots/<int:pk>/", SpotDetailView.as_view(), name="spot-detail"),
    path("api/spots/<int:pk>/share/", SpotShareView.as_view(), name="spot-share"),
    path("api/ranges/", RangeListView.as_view(), name="range-list"),
    path("api/ranges/<int:pk>/", RangeDetailView.as_view(), name="range-detail"),
    path("api/opponents/", OpponentListView.as_view(), name="opponent-list"),
    path("api/opponents/<int:pk>/", OpponentDetailView.as_view(), name="opponent-detail"),
    path("api/opponents/<int:pk>/showdowns/", OpponentShowdownsView.as_view(), name="opponent-showdowns"),
    path("api/opponents/<int:pk>/ledger/", OpponentLedgerView.as_view(), name="opponent-ledger"),
    path("api/tournaments/", TournamentListView.as_view(), name="tournament-list"),
    path("api/tournaments/summary/", TournamentSummaryView.as_view(), name="tournament-summary"),
    path("api/tournaments/<int:pk>/", TournamentDetailView.as_view(), name="tournament-detail"),
    path("api/tools/equity/", EquityToolView.as_view(), name="equity-tool"),
    path("api/shares/", ShareListView.as_view(), name="share-list"),
    path("api/shares/<int:pk>/", ShareDetailView.as_view(), name="share-detail"),
    path("api/public/shares/<str:slug>/", PublicShareView.as_view(), name="public-share"),
    path("api/practice/", include("practice.urls")),
    path("api/leagues/", include("leagues.urls")),
]

# The schema and Swagger UI describe every endpoint, so keep them out of prod.
if settings.DJANGO_ENV != "prod":
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
