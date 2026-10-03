import secrets

from django.conf import settings
from django.db import models


def generate_client_token():
    return secrets.token_hex(16)


class ClientToken(models.Model):
    """The token the tracker client sends to submit data for a user.

    Stored as-is, not hashed, so the user can see and copy it on their settings
    page whenever they set up a tracker. Every user gets one when created.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_token"
    )
    key = models.CharField(max_length=32, unique=True, default=generate_client_token, editable=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Client token of {self.user}"
