from rest_framework import serializers


class TokenResponseSerializer(serializers.Serializer):
    token_value = serializers.CharField(help_text="토큰 값")
    expiry = serializers.DateTimeField(help_text="만료 일시")
