import binascii
from hmac import compare_digest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from utils.exceptions import TokenAuthenticationFailed

from .crypto import hash_token
from .models import AuthToken

User = get_user_model()

# from zappa.asynchronous import task
# @task
# def update_auth_token_expiry(auth_token_digest):
#     new_expiry = timezone.now() + settings.AUTH_TOKEN_SETTING["TOKEN_TTL"]
#     AuthToken.objects.filter(digest=auth_token_digest).update(expiry=new_expiry)


class BaseTokenAuthenticationMixin:
    """
    Customized version of Django Rest Knox TokenAuthentication.
    Main changes:
    1. Read key values from django.conf settings instead of separate settings.
    2. Remove signal-based pattern.

    - Description of Django Rest Knox TokenAuthentication
    This authentication scheme uses Knox AuthTokens for authentication.

    Similar to DRF's TokenAuthentication, it overrides a large amount of that
    authentication scheme to cope with the fact that Tokens are not stored
    in plaintext in the database

    If successful
    - `request.user` will be a django `User` instance
    - `request.auth` will be an `AuthToken` instance

    """

    def _authenticate_credentials(self, token):
        """
        Due to the random nature of hashing a value, this must inspect
        each auth_token individually to find the correct one.

        Tokens that have expired will be deleted and skipped
        """
        for auth_token in AuthToken.objects.filter(token_key=token[:8]):
            if self._cleanup_token(auth_token):
                continue
            try:
                digest = hash_token(token)
            except TypeError, binascii.Error:
                raise TokenAuthenticationFailed()
            if compare_digest(digest, auth_token.digest):
                if settings.AUTH_TOKEN_SETTING["AUTO_REFRESH"] and auth_token.expiry:
                    self._renew_token(auth_token)
                return self._validate_user(
                    auth_token
                )  # TODO: Users pending deletion cannot authenticate even within recovery period.
        raise TokenAuthenticationFailed()

    def _renew_token(self, auth_token):
        current_expiry = auth_token.expiry
        new_expiry = timezone.now() + settings.AUTH_TOKEN_SETTING["TOKEN_TTL"]
        auth_token.expiry = new_expiry
        # delta = (new_expiry - current_expiry).total_seconds()
        # if delta > settings.AUTH_TOKEN_SETTING["MIN_REFRESH_INTERVAL_SECOND"]:
        #     update_auth_token_expiry(auth_token.digest)

    def _validate_user(self, auth_token):
        if not auth_token.user.is_active:
            raise TokenAuthenticationFailed()
        return (auth_token.user, auth_token)

    def _cleanup_token(self, auth_token):
        for user_auth_token in auth_token.user.authtoken_set.all():
            if user_auth_token.expiry < timezone.now():
                user_auth_token.delete()
        if auth_token.expiry is not None:
            if auth_token.expiry < timezone.now():
                auth_token.delete()
                return True
        return False


class StrictTokenAuthentication(BaseTokenAuthenticationMixin, BaseAuthentication):
    """
    Authentication for endpoints that require login.
    """

    def authenticate(self, request):
        auth = request.META.get(
            f"HTTP_{settings.AUTH_TOKEN_SETTING['AUTH_HEADER_PREFIX'].upper()}", None
        )
        if not auth:
            raise TokenAuthenticationFailed()
        return self._authenticate_credentials(auth)


class OptionalTokenAuthentication(BaseTokenAuthenticationMixin, BaseAuthentication):
    """
    Authentication for endpoints where login is optional.
    """

    def authenticate(self, request):
        auth = request.META.get(
            f"HTTP_{settings.AUTH_TOKEN_SETTING['AUTH_HEADER_PREFIX'].upper()}", None
        )
        if not auth:
            return None, None
        return self._authenticate_credentials(auth)

