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
            token_key=token_value[:8],
            digest=digest,
            user=user,
            expiry=expiry,
        )
        return instance, token_value


class AuthToken(models.Model):
    """인증 토큰"""

    objects = AuthTokenManager()

    digest = models.CharField(max_length=128, primary_key=True)
    token_key = models.CharField(
        max_length=8,
        db_index=True,
        help_text="db에 저장되는 token의 일부 값, DB가 탈취되어도 token을 알지 못하도록 일부만 저장",
    )
    user = models.ForeignKey(
        User,
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    created = models.DateTimeField(auto_now_add=True)
    expiry = models.DateTimeField(null=True, blank=True)

    # TODO - 마지막 업데이트 시각 넣기

    def __str__(self):
        return "%s : %s" % (self.digest, self.user)
