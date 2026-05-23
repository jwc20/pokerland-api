from factory import Sequence, SubFactory
from factory.django import DjangoModelFactory
from faker import Faker

from .models import (
    Customer,
    User,
)

fake = Faker("en_US")


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = Sequence(lambda n: f"dummy{n}@test.com")
    profile_name = Sequence(lambda n: f"dummy_name{n}")
    username = Sequence(lambda n: f"dummy_{n}")


class CustomerFactory(UserFactory):
    class Meta:
        model = Customer

    is_staff = False
    is_customer = True


class StaffFactory(UserFactory):
    class Meta:
        model = User

    is_staff = True
