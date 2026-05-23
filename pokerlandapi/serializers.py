from rest_framework import serializers


class EnvNameResponseSerializer(serializers.Serializer):
    env_name = serializers.CharField(help_text="환경명")
    datetime = serializers.DateTimeField(help_text="응답값이 마지막으로 캐시된 시각")
    ios_app_minimum_version = serializers.CharField(help_text="ios 최소 앱 버전")
    android_app_minimum_version = serializers.CharField(
        help_text="android 최소 앱 버전"
    )
