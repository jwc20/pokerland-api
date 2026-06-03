import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()


class GameLog(models.Model):
    """Stores a completed poker hand payload submitted by the desktop client."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="game_logs", null=True, blank=True
    )
    client_token_hash = models.CharField("Auth token", max_length=255)
    client = models.CharField("Client source", max_length=50)
    client_version = models.CharField("Client version", max_length=20)
    submitted_at = models.DateTimeField("Client submitted at", null=True, blank=True)
    payload = models.JSONField("Raw game payload")
    created_at = models.DateTimeField("Server received at", default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="idx_gamelog_created"),
            models.Index(
                fields=["client_token_hash"], name="idx_gamelog_client_token_hash"
            ),
        ]

    def __str__(self):
        return f"GameLog {self.id} ({self.client} v{self.client_version})"


class ErrorLog(models.Model):
    """Stores an error/debug payload submitted by the desktop client."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="error_logs", null=True, blank=True
    )
    token = models.CharField("Auth token", max_length=255)
    client = models.CharField("Client source", max_length=50)
    client_version = models.CharField("Client version", max_length=20)
    submitted_at = models.DateTimeField("Client submitted at", null=True, blank=True)
    payload = models.JSONField("Raw error payload")
    created_at = models.DateTimeField("Server received at", default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="idx_errorlog_created"),
            models.Index(fields=["token"], name="idx_errorlog_token"),
        ]

    def __str__(self):
        return f"ErrorLog {self.id} ({self.client} v{self.client_version})"
