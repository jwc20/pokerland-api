import hashlib
import secrets
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password
from django.db import models
from django.utils import timezone
from django_extensions.db.models import TimeStampedModel

from utils.choices import SocialLoginProviderChoices


CLIENT_TOKEN_PREFIX = "pokerland_"


def generate_client_token() -> str:
    return f"{CLIENT_TOKEN_PREFIX}{secrets.token_hex(32)}"


def hash_client_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
    username = models.CharField("Username", max_length=100, unique=True)
    username_changed_at = models.DateTimeField(
        "Username changed at", default=timezone.now
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
    client_token_hash = models.CharField(
        "Client token hash", max_length=64, unique=True, null=True, blank=True
    )

    is_superuser = models.BooleanField("Is system admin", default=False)
    is_staff = models.BooleanField("Is staff", default=False)
    is_customer = models.BooleanField("Is customer", default=True)

    USERNAME_FIELD = "email"

    objects = UserManager()

    def issue_client_token(self) -> str:
        while True:
            client_token = generate_client_token()
            client_token_hash = hash_client_token(client_token)
            if not User.objects.filter(client_token_hash=client_token_hash).exists():
                self.client_token_hash = client_token_hash
                self.save(update_fields=["client_token_hash"])
                return client_token


class CustomerManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_staff=False, is_customer=True)


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

    class Meta:
        indexes = [
            models.Index(
                fields=["email", "-created"], name="idx_confirmemail_email_created"
            ),
        ]


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
