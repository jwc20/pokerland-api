from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

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
]

# The schema and Swagger UI describe every endpoint, so keep them out of prod.
if settings.DJANGO_ENV != "prod":
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
