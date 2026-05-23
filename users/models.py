import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password
from django.db import models
from django.utils import timezone
from django_extensions.db.models import TimeStampedModel

from utils.choices import SocialLoginProviderChoices


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password, **extra_fields):
        return User.objects.create(
            email=email, password=make_password(password), **extra_fields
        )

    def create_superuser(self, login_id, password=None):
        extra_fields = {
            "is_superuser": True,
            "is_staff": True,
        }
        return self.create_user(login_id, password, **extra_fields)


class User(AbstractBaseUser):
    """User model with base profile fields regardless of role."""

    email = models.EmailField(unique=True)
    profile_name = models.CharField("Profile name", max_length=100, db_index=True)
    username = models.CharField("Profile tag", max_length=100, db_index=True)
    username_changed_at = models.DateTimeField(
        "Profile tag changed at", default=timezone.now
    )
    bio = models.CharField("Bio", max_length=255, default="")
    profile_image_url = models.URLField(
        "Profile image URL", default=None, null=True, blank=True, max_length=2048
    )
    is_active = models.BooleanField("Is active", default=True)
    date_joined = models.DateTimeField("Joined at", default=timezone.now)
    last_login = models.DateTimeField("Last login at", auto_now=True)
    password_changed_at = models.DateTimeField(
        "Password changed at", default=timezone.now
    )
    deletion_requested_at = models.DateTimeField(
        "Deletion requested at", null=True, blank=True
    )

    is_superuser = models.BooleanField("Is system admin", default=False)
    is_staff = models.BooleanField("Is staff", default=False)
    is_customer = models.BooleanField("Is customer", default=True)

    USERNAME_FIELD = "email"

    objects = UserManager()


class CustomerManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(is_creator=False, is_staff=False, is_customer=True)
        )


class Customer(User):
    class Meta:
        proxy = True

    objects = CustomerManager()


class StaffManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_staff=True)


class Staff(User):
    class Meta:
        proxy = True


class ConfirmEmail(TimeStampedModel):
    """Email Confirm Model"""

    email = models.EmailField()
    confirm_code = models.CharField("Verification code", max_length=6)
    is_confirmed = models.BooleanField(default=False)


class SocialLoginIdentifier(TimeStampedModel):
    """Social Login Identifier Model (Google, Apple, etc.)"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    provider = models.CharField(
        "Social login provider", max_length=10, choices=SocialLoginProviderChoices
    )
    identifier = models.CharField(max_length=255)
    temp_access_token = models.CharField(max_length=255)
    email = models.EmailField()
