import time

from django.conf import settings
from django.utils import timezone
from django.views.decorators.cache import cache_page
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from auth_tokens.auth import StrictTokenAuthentication
from pokerlandapi.serializers import EnvNameResponseSerializer
from utils.custom_swaggers.commons import (
    custom_swagger_auto_schema,
    get_swagger_response_dict,
)
from utils.exceptions import TokenAuthenticationFailed
from utils.permissions import ApiPermission, SwaggerDocumentPermission

schema_view = get_schema_view(
    openapi.Info(
        title=f"[{settings.ENV}] Pokerland API",
        default_version=settings.ALLOWED_VERSIONS[-1],
        description="""
        # SWAGGER document auto-generated via the drf-yasg library.
        """,
    ),
    public=True,
    permission_classes=(SwaggerDocumentPermission,),
)


@custom_swagger_auto_schema(
    operation_summary="Dummy endpoint for environment check (cache: 10s)",
    operation_description="""
    ### Authentication and Authorization
    1. api-key
    ---
    """,
    method="get",
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="""Dummy endpoint for environment checks; returns current environment.""",
            schema=EnvNameResponseSerializer,
        ),
    },
    security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
)
@cache_page(10)
@api_view(["GET"])
def env_name(_):
    time.sleep(1)
    return Response(
        data={
            "env_name": settings.ENV,
            "datetime": timezone.now(),
        },
        status=status.HTTP_200_OK,
    )
