# django_project/urls.py
from django.contrib import admin
from django.urls import path

from pokerlandapi.views import (
    schema_view,
)
from users.urls import urlpatterns as users_urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "swag/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
]

urlpatterns += users_urls
