from dj_rest_auth.jwt_auth import JWTCookieAuthentication as BaseJWTCookieAuthentication
from rest_framework.exceptions import AuthenticationFailed


class JWTCookieAuthentication(BaseJWTCookieAuthentication):
    """Treats an unusable access-token cookie as no credentials.

    dj-rest-auth rejects the request instead, even on login and registration, so
    a stale cookie (clock skew, a rotated signing key, a deleted user) would lock
    the user out until it expired. Endpoints that need a user still answer 401,
    which the client handles by refreshing. A token sent in the Authorization
    header is still rejected outright.
    """

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            if self.get_header(request) is not None:
                raise
            return None
