from rest_framework import serializers

from .models import ErrorLog, GameLog


class GameLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = GameLog
        fields = [
            "id",
            "token",
            "client",
            "client_version",
            "submitted_at",
            "payload",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class GameLogHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = GameLog
        fields = [
            "id",
            "user",
            "token",
            "client",
            "client_version",
            "submitted_at",
            "payload",
            "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]


class ErrorLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorLog
        fields = [
            "id",
            "token",
            "client",
            "client_version",
            "submitted_at",
            "payload",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
