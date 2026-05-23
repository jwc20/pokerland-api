from rest_framework import serializers


class EnvNameResponseSerializer(serializers.Serializer):
    env_name = serializers.CharField(help_text="Environment name")
    datetime = serializers.DateTimeField(help_text="Last cached timestamp of the response")
    ios_app_minimum_version = serializers.CharField(help_text="Minimum iOS app version")
    android_app_minimum_version = serializers.CharField(
        help_text="Minimum Android app version"
    )
