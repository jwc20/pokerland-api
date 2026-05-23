import json

from django.conf import settings
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
from packaging import version
from packaging.version import InvalidVersion
from rest_framework import status


class AppVersionMiddleware(MiddlewareMixin):
    def process_request(self, request):
        try:
            request.app_version = version.Version(
                request.headers.get("app-version", None)
            )
        except TypeError, InvalidVersion:
            request.app_version = None
        request.api_key = request.headers.get("api-key", None)
        request.os_type = request.headers.get("os-type", None)

    def process_view(self, request, *args, **kwargs):
        if settings.USE_IN_LOCAL:
            return
        if request.user and request.user.is_superuser:
            return
        if settings.ENV_NAME_CHECK_URL in request.resolver_match.route:
            return
        if "essentory_swagger" in request.resolver_match.route:
            return

        # minimum_version = self._get_minimum_app_version(request.os_type)
        # if request.app_version < minimum_version:
        #     return HttpResponse(
        #         content=json.dumps(
        #             {
        #                 "detail": "minimum_app_version_violation",
        #             }
        #         ),
        #         content_type="application/json",
        #         status=status.HTTP_400_BAD_REQUEST,
        #     )

    # def _get_minimum_app_version(self, os_type: str):
    #     if os_type == "ios":
    #         return settings.IOS_MINIMUM_APP_VERSION
    #     elif os_type == "android":
    #         return settings.ANDROID_MINIMUM_APP_VERSION
    #     else:
    #         return settings.ETC_MINIMUM_APP_VERSION


class LanguageMiddleware(MiddlewareMixin):
    """
    Middleware that sets the language for the current request based on
    the 'Accept-Language' header.
    """

    def process_request(self, request):
        # Get the Accept-Language header
        accept_language = request.headers.get("Accept-Language", "")

        # Default to Korean
        request.language = "ko"

        # Check if English is preferred
        if accept_language and accept_language.lower().startswith("en"):
            request.language = "en"

        return None
