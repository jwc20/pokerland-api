"""OpenAPI extensions that make the schema match this project's auth setup.

drf-spectacular's dj-rest-auth extensions describe dj-rest-auth's defaults. With
JWT_AUTH_HTTPONLY the refresh token travels only in its cookie, and with
JWT_AUTH_RETURN_EXPIRATION login also returns expiration times. pokerland-client
generates its types from this schema, so they have to match the real responses.

urls.py imports this module, which registers the extensions.
"""

from dj_rest_auth.app_settings import api_settings as rest_auth_settings
from dj_rest_auth.views import LoginView
from drf_spectacular.contrib.rest_auth import SimpleJWTCookieScheme
from drf_spectacular.extensions import (
    OpenApiAuthenticationExtension,
    OpenApiSerializerExtension,
    OpenApiViewExtension,
)
from drf_spectacular.utils import extend_schema
from rest_framework import serializers


class JWTCookieAuthenticationScheme(SimpleJWTCookieScheme):
    # drf-spectacular matches authentication classes exactly, not subclasses.
    target_class = "pokerlandapi.authentication.JWTCookieAuthentication"


class LoginViewExtension(OpenApiViewExtension):
    target_class = "dj_rest_auth.views.LoginView"
    priority = 1  # over drf-spectacular's, which ignores JWT_AUTH_RETURN_EXPIRATION

    def view_replacement(self):
        class Fixed(self.target_class):
            @extend_schema(responses=LoginView().get_response_serializer())
            def post(self, request, *args, **kwargs):
                pass  # pragma: no cover

        return Fixed


class JWTWithExpirationSerializerExtension(OpenApiSerializerExtension):
    target_class = "dj_rest_auth.serializers.JWTSerializerWithExpiration"

    def get_name(self):
        return "JWT"

    def map_serializer(self, auto_schema, direction):
        class Fixed(self.target_class):
            user = rest_auth_settings.USER_DETAILS_SERIALIZER()
            refresh = serializers.CharField(help_text="Empty: the refresh token is only set as a cookie.")

        return auto_schema._map_serializer(Fixed, direction)


class CookieTokenRefreshSerializerExtension(OpenApiSerializerExtension):
    target_class = "dj_rest_auth.jwt_auth.CookieTokenRefreshSerializer"
    priority = 1  # over drf-spectacular's, which requires `refresh` in the body

    def get_name(self):
        return "TokenRefresh"

    def map_serializer(self, auto_schema, direction):
        class Fixed(serializers.Serializer):
            refresh = serializers.CharField(
                write_only=True, required=False, help_text="Omit to use the refresh-token cookie."
            )
            access = serializers.CharField(read_only=True)
            access_expiration = serializers.DateTimeField(read_only=True)

        return auto_schema._map_serializer(Fixed, direction)


class ClientTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "tracker.authentication.ClientTokenAuthentication"
    name = "clientToken"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "`Token <client token>`, as the trackers send it.",
        }
