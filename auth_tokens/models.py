from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from . import crypto

User = get_user_model()


class AuthTokenManager(models.Manager):
    def create(self, user, expiry=settings.AUTH_TOKEN_SETTING["TOKEN_TTL"]):
        token_value = crypto.create_token_string()
        digest = crypto.hash_token(token_value)

        if expiry is not None:
            expiry = timezone.now() + expiry

        instance = super(AuthTokenManager, self).create(
            token_key=token_value,
            digest=digest,
            user=user,
            expiry=expiry,
        )
        return instance, token_value


class AuthToken(models.Model):
    """Authentication token."""

    objects = AuthTokenManager()

    digest = models.CharField(max_length=128, primary_key=True)
    token_key = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Partial token value stored in DB to avoid exposing full token if compromised.",
    )
    user = models.ForeignKey(
        User,
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    created = models.DateTimeField(auto_now_add=True)
    expiry = models.DateTimeField(null=True, blank=True)

    # TODO - Add last-updated timestamp.

    def __str__(self):
        return "%s : %s" % (self.digest, self.user)
