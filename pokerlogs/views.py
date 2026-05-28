import gzip
import json
import logging

from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.response import Response

from auth_tokens.auth import StrictTokenAuthentication
from utils.custom_swaggers.commons import (
    custom_swagger_auto_schema,
    get_swagger_response_dict,
)
from utils.exceptions import TokenAuthenticationFailed
from utils.paginations import ApiPageNumberPagination
from utils.permissions import ApiPermission

from .models import ErrorLog, GameLog
from .serializers import ErrorLogSerializer, GameLogHistorySerializer, GameLogSerializer

logger = logging.getLogger(__name__)

SWAGGER_TAG_POKERLOGS = ["Poker Logs"]

# Keys injected by the client's _add_base_data(); stored in dedicated columns.
_META_KEYS = {"token", "client", "client_version", "submitted_at"}


def _decode_gzip_body(request) -> dict:
    """Decode a gzip-compressed JSON request body.

    The desktop client sends ``Content-Encoding: gzip`` with a JSON payload.
    Django / DRF will *not* automatically decompress gzip request bodies, so
    we handle it manually here.
    """
    encoding = request.META.get("HTTP_CONTENT_ENCODING", "").lower()
    if encoding == "gzip":
        raw_body = gzip.decompress(request.body)
    else:
        raw_body = request.body
    return json.loads(raw_body)


def _extract_meta(data: dict) -> tuple[dict, dict]:
    """Split incoming blob into meta fields and the remaining payload."""
    meta = {k: data.get(k) for k in _META_KEYS}
    payload = {k: v for k, v in data.items() if k not in _META_KEYS}
    return meta, payload


class AddGameAPIView(GenericAPIView):
    """Receive a completed hand payload from the desktop client."""

    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = GameLogSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_POKERLOGS,
        operation_id="log_add_game",
        operation_summary="Submit a completed poker hand",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        Accepts a gzip-compressed JSON body sent by the desktop poker client.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_201_CREATED: GameLogSerializer},
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        data = _decode_gzip_body(request)
        meta, payload = _extract_meta(data)

        game_log = GameLog.objects.create(
            token=meta.get("token", ""),
            client=meta.get("client", ""),
            client_version=meta.get("client_version", ""),
            submitted_at=meta.get("submitted_at"),
            payload=payload,
        )

        return Response(
            status=status.HTTP_201_CREATED,
            data=GameLogSerializer(game_log).data,
        )


class MyGameHistoryAPIView(ListAPIView):
    """Return the authenticated user's completed hand history."""

    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = GameLogSerializer
    pagination_class = ApiPageNumberPagination

    def get_queryset(self):
        return GameLog.objects.filter(user=self.request.user)

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_POKERLOGS,
        operation_id="log_my_game_history",
        operation_summary="Get my game history logs",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        Returns the authenticated user's completed poker hand logs.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: GameLogSerializer(many=True)},
            api_exceptions=[TokenAuthenticationFailed],
        ),
        # security=[
        #     {"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}},
        #     {"Token": {"type": "apiKey", "name": "TOKEN", "in": "header"}},
        # ],
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class GameHistoryAPIView(ListAPIView):
    """Return completed hand history across all users."""

    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = GameLogHistorySerializer
    pagination_class = ApiPageNumberPagination

    def get_queryset(self):
        user = self.request.user
        # if not (user.is_staff or user.is_superuser):
        #     raise PermissionDenied("You do not have permission to view all game logs.")
        return GameLog.objects.all()

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_POKERLOGS,
        operation_id="log_game_history",
        operation_summary="Get all users' game history logs",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (staff or superuser required)
        ---
        Returns completed poker hand logs across all users.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: GameLogHistorySerializer(many=True)},
            api_exceptions=[TokenAuthenticationFailed],
        ),
        # security=[
        #     {"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}},
        #     {"Token": {"type": "apiKey", "name": "TOKEN", "in": "header"}},
        # ],
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class LogErrorsAPIView(GenericAPIView):
    """Receive an error/debug payload from the desktop client."""

    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = ErrorLogSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_POKERLOGS,
        operation_id="log_log_errors",
        operation_summary="Submit an error or debug report",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        Accepts a gzip-compressed JSON body sent by the desktop poker client.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_201_CREATED: ErrorLogSerializer},
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        data = _decode_gzip_body(request)
        meta, payload = _extract_meta(data)

        error_log = ErrorLog.objects.create(
            token=meta.get("token", ""),
            client=meta.get("client", ""),
            client_version=meta.get("client_version", ""),
            submitted_at=meta.get("submitted_at"),
            payload=payload,
        )

        return Response(
            status=status.HTTP_201_CREATED,
            data=ErrorLogSerializer(error_log).data,
        )
