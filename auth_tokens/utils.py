import datetime
from typing import Tuple

from django.contrib.auth import get_user_model

from auth_tokens.models import AuthToken
from utils.exceptions import AuthTokenDeleteFailed

User = get_user_model()


class CreateToken:
    def __init__(self, user: User):
        self.user = user

    def create(self) -> Tuple[str, datetime.datetime]:
        auth_token, token_value = AuthToken.objects.create(user=self.user)
        return token_value, auth_token.expiry


class DeleteToken:
    def __init__(self, user: User, auth_token: AuthToken = None):
        self.user = user
        self.auth_token = auth_token

    def delete(self):
        deleted_info = self.user.authtoken_set.filter(
            digest=self.auth_token.digest
        ).delete()
        if deleted_info[0] != 1:
            raise AuthTokenDeleteFailed()

    def delete_all(self):
        self.user.authtoken_set.all().delete()
