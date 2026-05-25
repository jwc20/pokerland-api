# django_project/urls.py
from django.contrib import admin
from django.urls import path

from pokerlandapi.views import (
    schema_view,
)
from pokerlogs.urls import urlpatterns as pokerlogs_urls
from users.urls import urlpatterns as users_urls
from utils.custom_swaggers.renderers import CustomSwaggerUIRenderer

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "swag/",
        schema_view.as_cached_view(
            cache_timeout=0,
            renderer_classes=(CustomSwaggerUIRenderer, *schema_view.renderer_classes),
        ),
        name="schema-swagger-ui",
    ),
]

urlpatterns += users_urls
urlpatterns += pokerlogs_urls
