from django.conf import settings
from django.db import models


class LogStream(models.Model):
    """One hand-history file on a user's machine, as uploaded by their tracker.

    The tracker derives `stream_id` from the file's fingerprint (see
    protocol/PROTOCOL.md in pokerland-trackers), so the same file always maps to
    the same stream for a user, even after the tracker loses its local state.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="log_streams")
    stream_id = models.UUIDField()
    source = models.CharField(max_length=32)  # e.g. "pokerstars"
    platform = models.CharField(max_length=16)  # windows | macos | linux
    client_version = models.CharField(max_length=32)
    path_hint = models.CharField(max_length=512, blank=True)
    fingerprint = models.CharField(max_length=64)
    # Bytes stored so far; the next chunk must start here.
    acked_offset = models.BigIntegerField(default=0)
    # Bytes the parser has consumed, and what it needs to continue mid-hand.
    parsed_offset = models.BigIntegerField(default=0)
    parser_state = models.JSONField(default=dict, blank=True)
    parser_version = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    last_chunk_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "stream_id"), name="unique_stream_per_user"),
        ]

    def __str__(self):
        return f"{self.user} {self.path_hint or self.stream_id}"


class LogChunk(models.Model):
    """A gzipped byte range of a stream, kept in raw storage until parsed."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        PARSED = "parsed"
        FAILED = "failed"

    stream = models.ForeignKey(LogStream, on_delete=models.CASCADE, related_name="chunks")
    start_offset = models.BigIntegerField()
    end_offset = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    compressed_size = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    parsed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("stream", "start_offset"), name="unique_chunk_start_per_stream"),
        ]
        ordering = ("start_offset",)

    def __str__(self):
        return f"{self.stream_id} [{self.start_offset}, {self.end_offset})"
