import factory
from factory.django import DjangoModelFactory

from .models import (
    ConfirmEmail,
    Customer,
    SocialLoginIdentifier,
    Staff,
    User,
)


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Faker("email")
    profile_name = factory.Faker("name")
    username = factory.Sequence(lambda n: f"user_{n}")
    bio = factory.Faker("sentence")
    password = factory.PostGenerationMethodCall("set_password", "DefaultPass1!")


class CustomerFactory(UserFactory):
    class Meta:
        model = Customer

    is_staff = False
    is_customer = True


class StaffFactory(UserFactory):
    class Meta:
        model = Staff

    is_staff = True


class ConfirmEmailFactory(DjangoModelFactory):
    class Meta:
        model = ConfirmEmail

    email = factory.Faker("email")
    confirm_code = factory.LazyFunction(lambda: "000000")
    is_confirmed = False


class SocialLoginIdentifierFactory(DjangoModelFactory):
    class Meta:
        model = SocialLoginIdentifier

    user = factory.SubFactory(UserFactory)
    provider = "google"
    identifier = factory.Faker("uuid4")
    temp_access_token = factory.Faker("sha256")
    email = factory.LazyAttribute(lambda obj: obj.user.email if obj.user else "test@example.com")
