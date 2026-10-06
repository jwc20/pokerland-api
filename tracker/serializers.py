from rest_framework import serializers

from tracker.models import LogStream


class MeSerializer(serializers.Serializer):
    username = serializers.CharField()


class ConfigSerializer(serializers.Serializer):
    min_version = serializers.CharField()
    poll_interval_seconds = serializers.IntegerField()
    flush_interval_seconds = serializers.IntegerField()
    flush_bytes = serializers.IntegerField()
    max_read_bytes = serializers.IntegerField()
    max_chunk_bytes = serializers.IntegerField()


class StreamRegistrationSerializer(serializers.ModelSerializer):
    fingerprint = serializers.RegexField(r"^[0-9a-f]{64}$")

    class Meta:
        model = LogStream
        fields = ("source", "platform", "client_version", "path_hint", "fingerprint")


class StreamAckSerializer(serializers.Serializer):
    stream_id = serializers.UUIDField()
    acked_offset = serializers.IntegerField()


class ChunkAckSerializer(serializers.Serializer):
    acked_offset = serializers.IntegerField()


class ChunkRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField()
    acked_offset = serializers.IntegerField(required=False)


class TrackerStatusSerializer(serializers.Serializer):
    """What the web app shows a user about their tracker."""

    last_upload_at = serializers.DateTimeField(allow_null=True)
    file_count = serializers.IntegerField()
    hands_seen = serializers.IntegerField()
    platforms = serializers.ListField(child=serializers.CharField())
    client_versions = serializers.ListField(child=serializers.CharField())
