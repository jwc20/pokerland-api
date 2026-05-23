from django.conf import settings
from rest_framework.permissions import BasePermission

from utils.commons import is_test_env


class ApiPermission(BasePermission):
    def has_permission(self, request, view):

        if request.user and request.user.is_superuser:
            return True
        if is_test_env():
            return True
        if not self._check_api_key(
            api_key=request.headers.get("api-key", None),
        ):
            return False

        return True

    @staticmethod
    def _check_api_key(api_key: str):
        if settings.USE_IN_LOCAL:
            return True
        else:
            return settings.API_KEY == api_key


class SwaggerDocumentPermission(BasePermission):
    def has_permission(self, request, view):
        if settings.USE_IN_LOCAL:
            return True
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0]
        else:
            ip_address = request.META.get("REMOTE_ADDR")

        return ip_address in settings.ALLOWED_IP_ADDRESSES


class ChannelSubscriberPermission(BasePermission):
    """Channel subscriber permission."""

    def has_permission(self, request, view):
        # TODO - Add permission checks for users with channel access rights.

        return True


class ChannelAdminPermission(BasePermission):
    """Channel admin permission."""

    def has_permission(self, request, view):
        return True
