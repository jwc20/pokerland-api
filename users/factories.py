from factory import Sequence, SubFactory
from factory.django import DjangoModelFactory
from faker import Faker

from .models import (
    AdAgreement,
    AdNightAgreement,
    Creator,
    CreatorLink,
    Customer,
    User,
    UserBlock,
)

fake = Faker("ko_KR")


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = Sequence(lambda n: f"dummy{n}@test.com")
    name = Sequence(lambda n: f"dummy_name{n}")
    user_tag = Sequence(lambda n: f"dummy_{n}")


class CustomerFactory(UserFactory):
    class Meta:
        model = Customer

    is_creator = False
    is_staff = False


class CreatorFactory(UserFactory):
    class Meta:
        model = Creator

    is_creator = True


class AdAgreementFactory(DjangoModelFactory):
    class Meta:
        model = AdAgreement

    user = SubFactory(UserFactory)


class AdNightAgreementFactory(DjangoModelFactory):
    class Meta:
        model = AdNightAgreement

    user = SubFactory(UserFactory)


class CreatorLinkFactory(DjangoModelFactory):
    class Meta:
        model = CreatorLink

    user = SubFactory(UserFactory)
    url = fake.url()


class UserBlockFactory(DjangoModelFactory):
    class Meta:
        model = UserBlock

    user = SubFactory(UserFactory)
    blocked_user = SubFactory(UserFactory)
