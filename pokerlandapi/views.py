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
        title=f"[{settings.ENV}] Essentory API",
        default_version=settings.ALLOWED_VERSIONS[-1],
        description=f"""
# drf-yasg 라이브러리를 통해 자동 생성된 SWAGGER 형식의 문서
""",
    ),
    public=True,
    permission_classes=(SwaggerDocumentPermission,),
)


@custom_swagger_auto_schema(
    operation_summary="환경명 체크를 위한 dummy(캐시: 10초)",
    operation_description="""
    ### 인증 및 권한
    1. api-key
    ---
    """,
    method="get",
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="""환경명 체크를 위한 dummy, 환경을 보여줌""",
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
