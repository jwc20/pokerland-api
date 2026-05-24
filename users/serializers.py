from rest_framework import serializers

from auth_tokens.serializers import TokenResponseSerializer
from users.models import User
from utils.choices import SocialLoginProviderChoices
from utils.commons import PASSWORD_REGEX
from utils.serializers import ModelUpdateSerializer


class EmailNormalizationMixin:
    """Mixin that normalizes email fields to lowercase during validation."""

    def validate_email(self, value: str) -> str:
        """Normalize email to lowercase."""
        if value:
            return value.lower()
        return value


class UsernameNormalizationMixin:
    """Mixin that normalizes username fields to lowercase during validation."""

    def validate_username(self, value: str) -> str:
        """Normalize username to lowercase."""
        if value:
            return value.lower()
        return value


class UserEmailLoginSerializer(EmailNormalizationMixin, serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="Email used as login ID",
    )
    password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        min_length=8,
        help_text=f"Must match the following regex: {PASSWORD_REGEX}",
    )


class UserEmailSignupSerializer(
    EmailNormalizationMixin, UsernameNormalizationMixin, serializers.Serializer
):
    email = serializers.EmailField(
        required=True,
        help_text="Email used as login ID",
    )
    password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        min_length=8,
        help_text=f"Must match the following regex: {PASSWORD_REGEX}",
    )
    profile_name = serializers.CharField(
        max_length=100,
        help_text="Display name for the user profile",
    )
    username = serializers.CharField(
        max_length=100,
        help_text="Unique profile tag / handle",
    )
    bio = serializers.CharField(
        allow_blank=True,
        max_length=255,
        help_text="Short biography text",
    )


class UserMyProfileResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email",
            "profile_name",
            "username",
            "bio",
            "is_active",
            "date_joined",
            "last_login",
            "is_staff",
            "is_customer",
            "password_changed_at",
            "deletion_requested_at",
        ]


class UserSignupLoginResponseSerializer(serializers.Serializer):
    user = UserMyProfileResponseSerializer()
    token_info = TokenResponseSerializer()


class UserMyProfileUpdateSerializer(ModelUpdateSerializer):
    class Meta:
        model = User
        fields = [
            "profile_name",
            "username",
            "bio",
        ]


class UserEmailSendConfirmCodeSerializer(EmailNormalizationMixin, serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="Email address to send the verification code to",
    )


class UserEmailSendConfirmCodeResponseSerializer(serializers.Serializer):
    """For returning information about the expiry time"""

    expires_in_minutes = serializers.IntegerField(
        help_text="Number of minutes until the verification code expires",
    )
    created_at = serializers.DateTimeField(
        help_text="Timestamp when the verification code was created",
    )


class UserEmailCheckConfirmCodeSerializer(EmailNormalizationMixin, serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="Email address the verification code was sent to",
    )
    confirm_code = serializers.RegexField(
        regex=r"^\d{6}$",
        required=True,
        max_length=6,
        help_text="6-digit verification code",
    )


class UserEmailCheckConfirmCodeResponseSerializer(serializers.Serializer):
    is_confirmed = serializers.BooleanField()


class UserFindPwEmailSendConfirmCodeSerializer(
    EmailNormalizationMixin, serializers.Serializer
):
    email = serializers.EmailField(
        required=True,
        help_text="Registered email address for password reset",
    )


class UserFindPwEmailCheckConfirmCodeSerializer(
    EmailNormalizationMixin, serializers.Serializer
):
    email = serializers.EmailField(
        required=True,
        help_text="Registered email address for password reset",
    )
    confirm_code = serializers.RegexField(
        regex=r"^\d{6}$",
        required=True,
        max_length=6,
        help_text="6-digit verification code",
    )


class UserFindPwEmailCheckConfirmCodeResponseSerializer(serializers.Serializer):
    is_confirmed = serializers.BooleanField()
    user = UserMyProfileResponseSerializer(allow_null=True, required=False)
    token_info = TokenResponseSerializer(allow_null=True, required=False)


class UserEmailResetPwSerializer(EmailNormalizationMixin, serializers.Serializer):
    new_password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        required=True,
        min_length=8,
        help_text=f"New password. Must match: {PASSWORD_REGEX}",
    )
    email = serializers.EmailField(
        required=False,
        help_text="Email address (required when not authenticated)",
    )


class UserEmailAvailabilitySerializer(EmailNormalizationMixin, serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="Email address to check availability for",
    )


class UserEmailAvailabilityResponseSerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


class UserTagAvailabilitySerializer(UsernameNormalizationMixin, serializers.Serializer):
    username = serializers.CharField(
        required=True,
        max_length=100,
        help_text="Username / profile tag to check availability for",
    )


class UsernameAvailabilityResponseSerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


class UsernameUpdateSerializer(UsernameNormalizationMixin, serializers.Serializer):
    username = serializers.CharField(
        required=True,
        max_length=100,
        help_text="New username / profile tag",
    )


class UserSocialSignupSerializer(UsernameNormalizationMixin, serializers.Serializer):
    social_uuid = serializers.UUIDField(
        help_text="UUID returned from the social check endpoint",
    )
    access_token = serializers.CharField(
        max_length=2048,
        help_text="Access token from social login provider",
    )
    profile_name = serializers.CharField(
        max_length=100,
        help_text="Display name for the user profile",
    )
    username = serializers.CharField(
        max_length=100,
        help_text="Unique profile tag / handle",
    )
    bio = serializers.CharField(
        allow_blank=True,
        max_length=255,
        help_text="Short biography text",
    )


class UserSocialCheckRequestSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=SocialLoginProviderChoices,
        help_text="Social login provider (e.g., google, apple)",
    )
    access_token = serializers.CharField(
        max_length=2048,
        help_text="Access token / ID token from social login provider",
    )


class UserSocialCheckResponseSerializer(serializers.Serializer):
    is_new = serializers.BooleanField()
    social_uuid = serializers.UUIDField()
    email = serializers.EmailField()


class UserSocialSigninSerializer(serializers.Serializer):
    social_uuid = serializers.UUIDField(
        help_text="UUID returned from the social check endpoint",
    )
    access_token = serializers.CharField(
        max_length=2048,
        help_text="Access token from social login provider",
    )
