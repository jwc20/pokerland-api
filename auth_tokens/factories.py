import datetime

import factory
from django.utils import timezone

from auth_tokens.models import AuthToken
from users.factories import UserFactory


class AuthTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuthToken

    user = factory.SubFactory(UserFactory)
    expiry = timezone.now() + datetime.timedelta(days=5)
