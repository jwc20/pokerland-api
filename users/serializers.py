from rest_framework import serializers

from auth_tokens.serializers import TokenResponseSerializer
from users.models import (
    User,
    AdAgreement,
    AdNightAgreement,
    CreatorLink,
    UserBlock,
)
from utils.choices import SocialLoginProviderChoices
from utils.commons import PASSWORD_REGEX
from utils.serializers import ModelUpdateSerializer, ApiPaginationSerializer


class UserEmailLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="사용자 로그인 ID용 이메일",
    )
    password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        min_length=8,
        help_text=f"다음 정규식을 따른다. {PASSWORD_REGEX}",
    )

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value


class UserEmailSignupSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        help_text="사용자 로그인 ID용 이메일",
    )
    password = serializers.RegexField(
        regex=PASSWORD_REGEX,
        min_length=8,
        help_text=f"다음 정규식을 따른다. {PASSWORD_REGEX}",
    )
    name = serializers.CharField()
    user_tag = serializers.CharField()
    bio = serializers.CharField(allow_blank=True)
    is_ad_agreed = serializers.BooleanField()
    is_ad_night_agreed = serializers.BooleanField()

    def validate_email(self, value):
        """Normalize email to lowercase"""
        if value:
            return value.lower()
        return value

    def validate_user_tag(self, value):
        """Normalize user_tag to lowercase"""
        if value:
            value = value.lower()
        return value


class AdAgreementResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdAgreement
        fields = [
            "modified",
            "is_agreed",
        ]


class AdNightAgreementResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdNightAgreement
        fields = [
            "modified",
            "is_agreed",
        ]


class CreatorLinkResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreatorLink
        fields = [
            "id",
            "title",
            "url",
        ]
        swagger_schema_fields = {"required": ["id", "title", "url"]}


class UserMyProfileResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email",
            "name",
            "user_tag",
            "profile_image_url",
            "bio",
            "is_active",
            "date_joined",
            "last_login",
            "is_staff",
            "is_creator",
            "ad_agreement",
            "ad_night_agreement",
            "subscribing_channel_ids",
            "managing_channel_ids",
            "creator_links",
            "password_changed_at",
            "deletion_requested_at",
        ]

    ad_agreement = AdAgreementResponseSerializer(many=False)
    ad_night_agreement = AdNightAgreementResponseSerializer(many=False)
    subscribing_channel_ids = serializers.ListField(
        child=serializers.IntegerField(), default=[]
    )
    managing_channel_ids = serializers.ListField(
        child=serializers.IntegerField(), default=[]
    )
    creator_links = CreatorLinkResponseSerializer(many=True)


class CreatorProfileResponseSerializer(UserMyProfileResponseSerializer):
    pass


class UserSignupLoginResponseSerializer(serializers.Serializer):
    user = UserMyProfileResponseSerializer()
    token_info = TokenResponseSerializer()


class CreatorLinkSerializer(ModelUpdateSerializer):
    id = serializers.UUIDField()

    class Meta:
        model = CreatorLink
        fields = [
            "id",
            "title",
            "url",
            "sort_order",
            "is_deleted",
        ]


class UserMyProfileUpdateSerializer(ModelUpdateSerializer):
    # Support both naming conventions for backward compatibility
    is_ad_agreement = serializers.BooleanField(required=False)
    is_ad_night_agreement = serializers.BooleanField(required=False)
    is_ad_agreed = serializers.BooleanField(required=False)
    is_ad_night_agreed = serializers.BooleanField(required=False)
    creator_links = serializers.ListField(child=CreatorLinkSerializer(), required=False)

    class Meta:
        model = User
        fields = [
            "name",
            "user_tag",
            "bio",
            "profile_image_url",
            "is_ad_agreement",
            "is_ad_night_agreement",
            "is_ad_agreed",
            "is_ad_night_agreed",
            "creator_links",
        ]

    def validate(self, data):
        # Handle both naming conventions
        # TODO
        if "is_ad_agreement" in data and "is_ad_agreed" not in data:
            data["is_ad_agreed"] = data.pop("is_ad_agreement")
        if "is_ad_night_agreement" in data and "is_ad_night_agreed" not in data:
            data["is_ad_night_agreed"] = data.pop("is_ad_night_agreement")
        return data


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
    user_tag = serializers.CharField(required=True)

    def validate_user_tag(self, value):
        """Normalize user_tag to lowercase"""
        if value:
            value = value.lower()
        return value


class UserTagAvailabilityResponseSerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


class UserTagUpdateSerializer(serializers.Serializer):
    user_tag = serializers.CharField(required=True)

    def validate_user_tag(self, value):
        """Normalize user_tag to lowercase"""
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
    name = serializers.CharField()
    user_tag = serializers.CharField()
    bio = serializers.CharField(allow_blank=True)
    is_ad_agreed = serializers.BooleanField()
    is_ad_night_agreed = serializers.BooleanField()

    def validate_user_tag(self, value):
        """Normalize user_tag to lowercase and add @ prefix if missing"""
        if value:
            value = value.lower()
            if not value.startswith("@"):
                value = f"@{value}"
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


class UserBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserBlock
        fields = [
            "id",
            "blocked_user",
            "created",
        ]


class UserBlockResponseSerializer(serializers.ModelSerializer):
    user_tag = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    profile_image_url = serializers.SerializerMethodField()

    def get_user_tag(self, obj):
        return obj.blocked_user.user_tag

    def get_name(self, obj):
        return obj.blocked_user.name

    def get_profile_image_url(self, obj):
        return obj.blocked_user.profile_image_url

    class Meta:
        model = UserBlock
        fields = [
            "id",
            "user_tag",
            "name",
            "profile_image_url",
            "created",
        ]


class PaginatedBlockedUsersResponseSerializer(ApiPaginationSerializer):
    results = UserBlockResponseSerializer(many=True, help_text="차단한 사용자 목록")


class BlockedUsersResponseSerializer(serializers.ModelSerializer):
    user_tag = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    profile_image_url = serializers.SerializerMethodField()

    def get_user_tag(self, obj):
        return obj.blocked_user.user_tag

    def get_name(self, obj):
        return obj.blocked_user.name

    def get_profile_image_url(self, obj):
        return obj.blocked_user.profile_image_url

    class Meta:
        model = UserBlock
        fields = [
            "id",
            "blocked_user",
            "user_tag",
            "name",
            "profile_image_url",
            "created",
        ]
        swagger_schema_fields = {"required": ["id", "blocked_user", "created"]}
