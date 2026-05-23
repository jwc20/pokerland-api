import logging
import random

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction, IntegrityError
from django.utils import timezone
from datetime import timedelta

from auth_tokens.utils import CreateToken
from utils.choices import LoginIdDuplicateCheckResultChoices, SocialLoginProviderChoices
from utils.email_service import EmailService
from utils.exceptions import (
    AlreadyEnrolledEmail,
    InvalidLoginInfo,
    NotEnrolledEmail,
    EmailVerificationCodeExpired,
    EmailVerificationRateLimited,
    InvalidVerificationCode,
    TokenAuthenticationFailed,
    SocialUserExists,
    SocialAccessTokenExpired,
    SocialLoginIdentifierNotFound,
    AccountNotMarkedForDeletion,
    RecoveryPeriodExpired,
    UserDoesNotExist,
    CannotBlockYourself,
    UserTagUpdateRestricted,
)
from .models import (
    AdAgreement,
    AdNightAgreement,
    User,
    ConfirmEmail,
    CreatorLink,
    SocialLoginIdentifier,
    UserBlock,
)
from .social_auth import SocialAuthModule, GoogleAuthModule, AppleAuthModule


class CustomerAccountHandler:
    """
    일반 사용자(후원자)의 계정 관련 모듈

    기본적으로 모든 계정은 고객 권한을 가짐
    """

    def __init__(self, **kwargs):
        self.user = kwargs.get("user", None)
        self.email = kwargs.get("email", None)
        self.password = kwargs.get("password", None)
        self.name = kwargs.get("name", None)
        self.user_tag = kwargs.get("user_tag", None)
        self.bio = kwargs.get("bio", "")
        self.is_ad_agreed = kwargs.get("is_ad_agreed", None)
        self.is_ad_night_agreed = kwargs.get("is_ad_night_agreed", None)

    @transaction.atomic
    def email_signup(self, language="ko"):
        # Convert email to lowercase
        email = self.email.lower() if self.email else None

        # Format user_tag: convert to lowercase and ensure @ prefix
        user_tag = self.user_tag.lower() if self.user_tag else None

        try:
            user = User.objects.create_user(
                email=email,
                password=self.password,
                name=self.name,
                user_tag=user_tag,
                bio=self.bio,
            )
        except IntegrityError:
            raise AlreadyEnrolledEmail()

        AdAgreement.objects.create(
            user=user,
            is_agreed=self.is_ad_agreed,
        )
        AdNightAgreement.objects.create(
            user=user,
            is_agreed=self.is_ad_night_agreed,
        )

        is_prod = settings.ENV == "prod"
        if is_prod:
            EmailService.send_template_email(
                subject="Essentory 가입을 환영합니다",
                recipients=email,
                template_name="welcome",
                context={"name": self.name},
                async_send=True,
                language=language,
            )

        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def login_id_duplicate_check(self):
        # TODO - 탈퇴나 휴면은 어떻게할지 살짝 고민 필요
        # Ensure email is lowercase and check case-insensitively
        email = self.email.lower() if self.email else None
        if User.objects.filter(login_id__iexact=email).exists():
            return LoginIdDuplicateCheckResultChoices.duplicated
        else:
            return LoginIdDuplicateCheckResultChoices.unique

    def login(self):
        user = self._authenticate()
        # 첫번째 토큰은 만료 시켜야 하나?
        # 두번째 토큰 부터는 expiry 를 좀더 짧게주는게 어떨까?
        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def update_profile(self, **kwargs):
        is_ad_agreed = kwargs.pop("is_ad_agreed", None)
        is_ad_night_agreed = kwargs.pop("is_ad_night_agreed", None)
        creator_links = kwargs.pop("creator_links", [])

        # Format fields for update
        if "email" in kwargs and kwargs["email"]:
            kwargs["email"] = kwargs["email"].lower()

        if "user_tag" in kwargs and kwargs["user_tag"]:
            kwargs["user_tag"] = kwargs["user_tag"].lower()

        if is_ad_agreed is not None:
            ad_agreement = AdAgreement.objects.get(user=self.user)
            ad_agreement.is_agreed = is_ad_agreed
            ad_agreement.save()
        if is_ad_night_agreed is not None:
            ad_night_agreement = AdNightAgreement.objects.get(user=self.user)
            ad_night_agreement.is_agreed = is_ad_night_agreed
            ad_night_agreement.save()
        User.objects.filter(id=self.user.id).update(**kwargs)

        creator_links_to_create = []
        for i, creator_link_info in enumerate(creator_links):
            creator_link_id = creator_link_info.pop("id", None)
            if creator_link_id:
                self.user.creatorlink_set.filter(id=str(creator_link_id)).update(
                    **creator_link_info
                )
            else:
                creator_links_to_create.append(
                    CreatorLink(
                        user=self.user,
                        **creator_link_info,
                    )
                )
        CreatorLink.objects.bulk_create(creator_links_to_create)
        self.user.refresh_from_db()
        return self.user

    def update_user_tag(self, user_tag):
        """
        사용자의 프로필 태그(user_tag)를 변경합니다.
        31일 내에 한 번만 변경할 수 있습니다.

        Args:
            user_tag: 변경할 프로필 태그

        Returns:
            User: 업데이트된 사용자 객체

        Raises:
            UserTagUpdateRestricted: 31일 내에 다시 태그를 변경하려고 할 때 발생
        """
        # Ensure user_tag is lowercase for consistency
        if user_tag:
            user_tag = user_tag.lower()

        # Check if user_tag is available (not used by other users)
        if (
            User.objects.filter(user_tag__iexact=user_tag)
            .exclude(id=self.user.id)
            .exists()
        ):
            raise AlreadyEnrolledEmail()  # Reusing this exception for tag uniqueness

        # Check if user has changed tag in the last 31 days
        thirty_one_days_ago = timezone.now() - timedelta(days=31)
        if (
            self.user.user_tag_changed_at
            and self.user.user_tag_changed_at > thirty_one_days_ago
        ):
            raise UserTagUpdateRestricted()

        old_user_tag = self.user.user_tag

        # Update the user_tag and record the change time, then cascade to related content
        with transaction.atomic():
            # Update user model
            User.objects.filter(id=self.user.id).update(
                user_tag=user_tag, user_tag_changed_at=timezone.now()
            )

            # Since user_tag is accessed via cached_property in content models,
            # we don't need to update the actual content tables

            # However, we should invalidate any caches that might store the user_tag separately
            # This is a good place to add cache invalidation if needed in the future

        # Refresh user from database
        self.user.refresh_from_db()
        return self.user

    def logout(self, token_value):
        self.user.authtoken_set.filter(token_key=token_value[:8]).delete()

    def find_email(self):
        # TODO - 나중에 전화번호 데이터 및 찾기 로직 들어가면 완성하기
        pass

    def reset_password(self, new_password, email=None, language="ko"):
        user = self.user
        # If no user is provided but email is, use the email to find the user
        if (not user or user.is_anonymous) and email:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                raise NotEnrolledEmail()

        # Ensure we have a user to work with
        if not user:
            raise NotEnrolledEmail()

        # Change password and update timestamp
        user.set_password(new_password)

        # Set password change timestamp
        now = timezone.now()
        user.password_changed_at = now
        user.save()

        is_prod = settings.ENV == "prod"
        if is_prod:
            EmailService.send_template_email(
                subject="Essentory 비밀번호가 변경되었습니다",
                recipients=user.email,
                template_name="password_changed",
                context={
                    "name": user.name,
                    "changed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                },
                async_send=True,
                language=language,
            )

    def _authenticate(self):
        # Ensure email is lowercase for authentication
        email = self.email.lower() if self.email else None

        user = authenticate(
            username=email,
            password=self.password,
        )
        if not user:
            try:
                potential_user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise InvalidLoginInfo()
            if potential_user.check_password(self.password):
                self.user = potential_user
                self.recover_account()  # can raise RecoveryPeriodExpired exception
                return potential_user
            raise InvalidLoginInfo()
        else:
            User.objects.filter(id=user.id).update(
                last_login=timezone.now(),
            )
            return user

    def send_confirm_code(self, email, is_signup=True, language="ko"):
        """
        Send a verification code to the specified email address.
        Handles rate limiting and environment-specific behavior.

        Args:
            email: The email address to send the code to
            is_signup: True if for signup, False if for password reset
            language: Language code ('ko' or 'en') for email templates

        Returns:
            Dict with created_at and expiry information

        Raises:
            AlreadyEnrolledEmail: If email exists during signup flow
            NotEnrolledEmail: If email doesn't exist during password reset flow
            EmailVerificationRateLimited: If too many requests from the same email
        """
        # Ensure email is lowercase for consistency
        email = email.lower() if email else None

        # Check if the email is valid for the requested flow
        if is_signup:
            # For signup: email should not already exist
            if User.objects.filter(email__iexact=email).exists():
                raise AlreadyEnrolledEmail()
        else:
            # For password reset: email must exist
            if not User.objects.filter(email__iexact=email).exists():
                raise NotEnrolledEmail()

        # Check for rate limiting (no more than 3 requests in 10 minutes)
        recent_time = timezone.now() - timedelta(minutes=10)
        recent_attempts = ConfirmEmail.objects.filter(
            email__iexact=email, created__gte=recent_time
        ).count()

        is_prod = settings.ENV == "prod"

        # Rate limit: max 3 attempts in 10 minutes
        if is_prod and recent_attempts >= 3:
            raise EmailVerificationRateLimited()

        # Generate verification code (always use random in prod, use 000000 in non-prod)
        verification_code = (
            "{:06d}".format(random.randint(0, 999999)) if is_prod else "000000"
        )

        # Create the confirmation record
        confirm_email = ConfirmEmail.objects.create(
            email=email,
            confirm_code=verification_code,
        )

        # Send email with verification code
        template_name = "password_reset" if not is_signup else "verification_code"
        subject = "비밀번호 재설정 코드" if not is_signup else "이메일 인증 코드"

        # Prepare template context
        context = {
            "code": verification_code,
            "expiry_minutes": settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES,
        }

        if is_prod:
            EmailService.send_template_email(
                subject=subject,
                recipients=email,
                template_name=template_name,
                context=context,
                async_send=True,
                language=language,
            )
        else:
            logging.info(f"Verification code for {email}: {verification_code}")

        # Return the confirmation object for expiry information
        return {
            "created_at": confirm_email.created,
            "expires_in_minutes": settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES,
        }

    def check_confirm_code(self, email, confirm_code):
        """
        Verify the confirmation code for a given email address.

        Args:
            email: The email to verify
            confirm_code: The confirmation code to check

        Returns:
            bool: True if the code is valid and confirmed, False otherwise

        Raises:
            EmailVerificationCodeExpired: If the verification code has expired
            InvalidVerificationCode: If the code doesn't match
        """
        # Ensure email is lowercase for consistency
        email = email.lower() if email else None

        #  allow 000000 in dev and local environments
        if confirm_code == "000000" and settings.ENV in ["dev", "local"]:
            # Get the most recent confirmation record for this email
            email_confirmation = (
                ConfirmEmail.objects.filter(
                    email__iexact=email,
                )
                .order_by("-created")
                .first()
            )

            # No confirmation record found
            if not email_confirmation:
                raise InvalidVerificationCode()

            # Check if code has expired
            expiry_time = email_confirmation.created + timedelta(
                minutes=settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
            )

            if timezone.now() > expiry_time:
                raise EmailVerificationCodeExpired()

            # Mark as confirmed
            email_confirmation.is_confirmed = True
            email_confirmation.save()
            return True

        # Regular validation for other cases
        # Get the most recent confirmation record for this email
        email_confirmation = (
            ConfirmEmail.objects.filter(
                email__iexact=email,
            )
            .order_by("-created")
            .first()
        )

        # No confirmation record found
        if not email_confirmation:
            raise InvalidVerificationCode()

        # Check if code has expired
        expiry_time = email_confirmation.created + timedelta(
            minutes=settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
        )

        if timezone.now() > expiry_time:
            raise EmailVerificationCodeExpired()

        # Check if the code matches
        if email_confirmation.confirm_code == confirm_code:
            # Mark as confirmed
            email_confirmation.is_confirmed = True
            email_confirmation.save()
            return True
        else:
            raise InvalidVerificationCode()

    def _check_confirmed_email(self, email):
        return ConfirmEmail.objects.filter(email=email, is_confirmed=True).exists()

    def force_login(self, email):
        user = User.objects.get(email=email)
        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    @transaction.atomic
    def delete_account(self):
        """
        계정 삭제(탈퇴) 처리 - 30일의 복구 기간이 제공됩니다

        계정 삭제는 즉시 이루어지지 않고, 30일 동안 계정은 비활성화됩니다.
        30일 이내에 계정을 복구할 수 있습니다.
        30일 후에는 계정 삭제가 완료됩니다.

        Returns:
            bool: True on successful deletion request

        Raises:
            ValueError: If no user is provided
        """
        if not self.user:
            raise ValueError("계정 삭제를 위해 사용자 정보가 필요합니다")

        # 1. Invalidate all auth tokens
        self.user.authtoken_set.all().delete()

        # 2. Mark user account for deletion
        self.user.is_active = False
        self.user.deletion_requested_at = timezone.now()
        self.user.save()

        # 3. Update related models
        # Set AdAgreement to false
        ad_agreement = AdAgreement.objects.get(user=self.user)
        ad_agreement.is_agreed = False
        ad_agreement.save()

        ad_night_agreement = AdNightAgreement.objects.get(user=self.user)
        ad_night_agreement.is_agreed = False
        ad_night_agreement.save()

        # 4. Remove creator links if any
        CreatorLink.objects.filter(user=self.user).update(is_deleted=True)

        # 5. Withdraw social login tokens(not delete)
        social_login_identifiers = self.user.socialloginidentifier_set.all()
        for social_login_identifier in social_login_identifiers:
            SocialAuthHandler(social_login_identifier.provider).withdrawal(
                social_login_identifier
            )

        return True

    @transaction.atomic
    def recover_account(self):
        """
        삭제 요청된 계정 복구 (30일 이내)

        Returns:
            bool: True on successful recovery

        Raises:
            ValueError: If no user is provided
            AccountNotMarkedForDeletion: If the account is not marked for deletion
            RecoveryPeriodExpired: If the 30-day recovery period has expired
        """
        if not self.user:
            raise ValueError("계정 복구를 위해 사용자 정보가 필요합니다")

        # Check if the account is marked for deletion
        if not self.user.deletion_requested_at:
            raise AccountNotMarkedForDeletion()

        # Check if the recovery period (30 days) has expired
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        if self.user.deletion_requested_at < thirty_days_ago:
            raise RecoveryPeriodExpired()

        # Reactivate the account
        self.user.is_active = True
        self.user.deletion_requested_at = None
        self.user.save()

        return True


class SocialAuthHandler:
    def __init__(self, provider):
        self.provider = provider
        self.module: SocialAuthModule = self.get_module()

    def get_module(self):
        if self.provider == SocialLoginProviderChoices.google:
            return GoogleAuthModule()
        elif self.provider == SocialLoginProviderChoices.apple:
            return AppleAuthModule()
        else:
            return None

    def check(self, access_token):
        """
        소셜 로그인 정보를 검증합니다

        Args:
            access_token: 소셜 로그인 제공자에서 발급받은 액세스 토큰

        Returns:
            social_uuid: 소셜 로그인 식별자
            email: 소셜 로그인 이메일
            is_new: 소셜 로그인 신규 가입 여부 (기존 이메일 계정이 있는 경우 해당 계정으로 로그인)

        Raises:
            TokenAuthenticationFailed: 토큰이 유효하지 않은 경우
        """
        if self.provider == None:
            raise ValueError("provider not found")
        identifier, email = self.module.check(access_token)

        if identifier is None and email is None:
            raise TokenAuthenticationFailed()

        # Check if the identifier already exists in our system
        if (
            SocialLoginIdentifier.objects.filter(identifier=identifier).exists()
            and not SocialLoginIdentifier.objects.filter(identifier=identifier)
            .first()
            .user
            is None
        ):
            social_login_identifier = SocialLoginIdentifier.objects.get(
                identifier=identifier
            )
            social_login_identifier.temp_access_token = access_token[:100]
            social_login_identifier.save()
            return social_login_identifier.id, email, False
        # Check if a user with the same email exists but not linked to this social identity
        elif email and User.objects.filter(email__iexact=email).exists():
            user = User.objects.get(email__iexact=email)
            social_login_identifier = SocialLoginIdentifier.objects.create(
                provider=self.provider,
                identifier=identifier,
                email=email,
                temp_access_token=access_token[:100],
                user=user,  # Link to existing user
            )
            return social_login_identifier.id, email, False  # Not a new user
        else:
            # New social login - create identifier without user (will be created during signup)
            social_login_identifier = SocialLoginIdentifier.objects.create(
                provider=self.provider,
                identifier=identifier,
                email=email,
                temp_access_token=access_token[:100],
            )
            return social_login_identifier.id, email, True

    @transaction.atomic
    def create_user(
        self,
        language,
        social_uuid,
        access_token,
        name,
        user_tag,
        bio,
        is_ad_agreed,
        is_ad_night_agreed,
    ):
        if not SocialLoginIdentifier.objects.filter(id=social_uuid).exists():
            raise SocialLoginIdentifierNotFound()
        social_login_identifier = SocialLoginIdentifier.objects.get(id=social_uuid)
        if social_login_identifier.user is not None:
            raise SocialUserExists()
        if social_login_identifier.temp_access_token != access_token[:100]:
            raise SocialAccessTokenExpired()

        user_tag = user_tag.lower() if user_tag else None

        if user_tag and user_tag.startswith("@"):
            user_tag = user_tag.replace("@", "") if user_tag else None

        try:
            user = User.objects.create_user(
                email=social_login_identifier.email.lower(),
                password=None,
                name=name,
                user_tag=user_tag,
                bio=bio,
            )
        except IntegrityError:
            raise AlreadyEnrolledEmail()

        social_login_identifier.user = user
        social_login_identifier.save()

        AdAgreement.objects.create(
            user=user,
            is_agreed=is_ad_agreed,
        )
        AdNightAgreement.objects.create(
            user=user,
            is_agreed=is_ad_night_agreed,
        )

        is_prod = settings.ENV == "prod"
        if is_prod:
            EmailService.send_template_email(
                subject="Essentory 가입을 환영합니다",
                recipients=social_login_identifier.email,
                template_name="welcome",
                context={"name": name},
                async_send=True,
                language=language,
            )

        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def login(self, social_uuid, access_token):
        if not SocialLoginIdentifier.objects.filter(id=social_uuid).exists():
            raise SocialLoginIdentifierNotFound()
        social_login_identifier = SocialLoginIdentifier.objects.get(id=social_uuid)
        if social_login_identifier.user is None:
            raise NotEnrolledEmail()
        if social_login_identifier.temp_access_token != access_token[:100]:
            raise SocialAccessTokenExpired()
        user = social_login_identifier.user
        user.last_login = timezone.now()
        user.save()
        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def withdrawal(self, social_login_identifier: SocialLoginIdentifier):
        self.module.withdrawal(social_login_identifier.identifier)


class UserBlockHandler:
    """
    사용자 차단 관련 기능을 처리하는 핸들러
    """

    def __init__(self, user=None):
        self.user = user

    def block_user(self, user_tag):
        """
        다른 사용자를 차단합니다.

        Args:
            user_tag: 차단할 사용자의 태그

        Returns:
            UserBlock: 생성된 차단 정보

        Raises:
            UserDoesNotExist: 차단할 사용자가 존재하지 않는 경우
            CannotBlockYourself: 자기 자신을 차단하려는 경우
        """
        # 차단할 사용자 검색 (대소문자 구분 없이)
        try:
            # Ensure user_tag is lowercase for case-insensitive matching
            user_tag = user_tag.lower() if user_tag else None
            blocked_user = User.objects.get(user_tag__iexact=user_tag)
        except User.DoesNotExist:
            raise UserDoesNotExist()

        # 자기 자신을 차단하려는 경우 예외 발생
        if blocked_user.id == self.user.id:
            raise CannotBlockYourself()

        # 이미 차단한 경우에는 그대로 반환
        user_block, created = UserBlock.objects.get_or_create(
            user=self.user, blocked_user=blocked_user
        )

        return user_block

    def unblock_user(self, user_tag):
        """
        사용자 차단을 해제합니다.

        Args:
            user_tag: 차단 해제할 사용자의 태그

        Returns:
            bool: 차단 해제 성공 여부

        Raises:
            UserDoesNotExist: 차단 해제할 사용자가 존재하지 않는 경우
        """
        # 차단 해제할 사용자 검색 (대소문자 구분 없이)
        try:
            # Ensure user_tag is lowercase for case-insensitive matching
            user_tag = user_tag.lower() if user_tag else None
            blocked_user = User.objects.get(user_tag__iexact=user_tag)
        except User.DoesNotExist:
            raise UserDoesNotExist()

        # 차단 정보 삭제
        deleted, _ = UserBlock.objects.filter(
            user=self.user, blocked_user=blocked_user
        ).delete()

        return deleted > 0

    def get_blocked_users(self):
        """
        사용자가 차단한 사용자 목록을 조회합니다.

        Returns:
            QuerySet: 차단한 사용자 목록
        """
        return UserBlock.objects.filter(user=self.user).select_related("blocked_user")

    def get_users_blocking_me(self):
        """
        사용자를 차단한 사용자 목록을 조회합니다.

        Returns:
            QuerySet: 나를 차단한 사용자 목록
        """
        return UserBlock.objects.filter(blocked_user=self.user).select_related("user")
