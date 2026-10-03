from rest_framework import serializers

from users.models import ClientToken


class ClientTokenSerializer(serializers.ModelSerializer):
    client_token = serializers.CharField(source="key", read_only=True)

    class Meta:
        model = ClientToken
        fields = ("client_token",)
