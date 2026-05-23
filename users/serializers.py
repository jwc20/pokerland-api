from rest_framework import serializers

from auth_tokens.serializers import TokenResponseSerializer
from users.models import User
from utils.choices import SocialLoginProviderChoices
from utils.commons import PASSWORD_REGEX
from utils.serializers import ModelUpdateSerializer


class UserEmailLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="Email used as login ID",
    )
    password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        min_length=8,
        help_text=f"Must match the following regex: {PASSWORD_REGEX}",
    )

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserEmailSignupSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="Email used as login ID",
    )
    password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        min_length=8,
        help_text=f"Must match the following regex: {PASSWORD_REGEX}",
    )
    profile_name = serializers.CharField()
    username = serializers.CharField()
    bio = serializers.CharField(allow_blank=True)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value

    def validate_username(self, value):
        """Normalize username to lowercase"""
        if value:
            value = value.lower()
        return value


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


class UserEmailSendConfirmCodeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserEmailSendConfirmCodeResponseSerializer(serializers.Serializer):
    """For returning information about the expiry time"""

    expires_in_minutes = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class UserEmailCheckConfirmCodeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    confirm_code = serializers.CharField(required=True)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserEmailCheckConfirmCodeResponseSerializer(serializers.Serializer):
    is_confirmed = serializers.BooleanField()


class UserFindPwEmailSendConfirmCodeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserFindPwEmailCheckConfirmCodeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    confirm_code = serializers.CharField(required=True)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserFindPwEmailCheckConfirmCodeResponseSerializer(serializers.Serializer):
    is_confirmed = serializers.BooleanField()
    user = UserMyProfileResponseSerializer(allow_null=True, required=False)
    token_info = TokenResponseSerializer(allow_null=True, required=False)


class UserEmailResetPwSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True)
    email = serializers.EmailField(required=False)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserEmailAvailabilitySerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserEmailAvailabilityResponseSerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


class UserTagAvailabilitySerializer(serializers.Serializer):
    username = serializers.CharField(required=True)

    def validate_username(self, value):
        """Normalize username to lowercase"""
        if value:
            value = value.lower()
        return value


class UsernameAvailabilityResponseSerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


class UsernameUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)

    def validate_username(self, value):
        if value:
            value = value.lower()
        return value


class UserDeleteAccountSerializer(serializers.Serializer):
    pass


class UserRecoverAccountSerializer(serializers.Serializer):
    pass


class UserSocialSignupSerializer(serializers.Serializer):
    social_uuid = serializers.UUIDField()
    access_token = serializers.CharField()
    profile_name = serializers.CharField()
    username = serializers.CharField()
    bio = serializers.CharField(allow_blank=True)

    def validate_username(self, value):
        if value:
            value = value.lower()
        return value


class UserSocialCheckRequestSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=SocialLoginProviderChoices)
    access_token = serializers.CharField()


class UserSocialCheckResponseSerializer(serializers.Serializer):
    is_new = serializers.BooleanField()
    social_uuid = serializers.UUIDField()
    email = serializers.EmailField()


class UserSocialSigninSerializer(serializers.Serializer):
    social_uuid = serializers.UUIDField()
    access_token = serializers.CharField()
