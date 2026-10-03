from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.generics import RetrieveAPIView

from users.serializers import ClientTokenSerializer


@method_decorator(never_cache, name="dispatch")  # it is a credential
class ClientTokenView(RetrieveAPIView):
    """The signed-in user's client token, for connecting the tracker client."""

    serializer_class = ClientTokenSerializer

    def get_object(self):
        return self.request.user.client_token
