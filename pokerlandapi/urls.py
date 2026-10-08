from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from hands.views import (
    CoachPresetsView,
    LeaksView,
    PurposeStatsView,
    ReviewView,
    SessionDetailView,
    SessionListView,
    SessionPatternsView,
    StatsView,
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
    path("api/review/", ReviewView.as_view(), name="review"),
    path("api/leaks/", LeaksView.as_view(), name="leaks"),
    path("api/leaks/presets/", CoachPresetsView.as_view(), name="coach-presets"),
    path("api/sessions/", SessionListView.as_view(), name="session-list"),
    path("api/sessions/patterns/", SessionPatternsView.as_view(), name="session-patterns"),
    path("api/sessions/<int:pk>/", SessionDetailView.as_view(), name="session-detail"),
    path("api/practice/", include("practice.urls")),
]

# The schema and Swagger UI describe every endpoint, so keep them out of prod.
if settings.DJANGO_ENV != "prod":
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
