from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from users.models import ClientToken


class ClientTokenAuthentication(BaseAuthentication):
    """Authenticates a tracker by its client token: `Authorization: Token <key>`.

    Only the tracker endpoints use it. The web app keeps its JWT cookies, so a
    leaked client token can upload hand histories but cannot sign in.
    """

    keyword = "Token"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword.lower().encode():
            return None
        if len(parts) != 2:
            raise AuthenticationFailed(_("Invalid token header."))
        try:
            token = ClientToken.objects.select_related("user").get(key=parts[1].decode())
        except ClientToken.DoesNotExist, UnicodeDecodeError:
            raise AuthenticationFailed(_("Invalid token.")) from None
        if not token.user.is_active:
            raise AuthenticationFailed(_("User inactive or deleted."))
        return token.user, token

    def authenticate_header(self, request):
        return self.keyword
