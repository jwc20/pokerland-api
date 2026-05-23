from rest_framework import serializers


class TokenResponseSerializer(serializers.Serializer):
    token_value = serializers.CharField(help_text="Token value")
    expiry = serializers.DateTimeField(help_text="Expiration timestamp")
