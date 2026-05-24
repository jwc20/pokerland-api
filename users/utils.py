import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.utils import timezone

from auth_tokens.utils import CreateToken
from utils.choices import LoginIdDuplicateCheckResultChoices, SocialLoginProviderChoices

from utils.exceptions import (
    AccountNotMarkedForDeletion,
    AlreadyEnrolledEmail,
    EmailVerificationCodeExpired,
    EmailVerificationRateLimited,
    InvalidLoginInfo,
    InvalidVerificationCode,
    NotEnrolledEmail,
    RecoveryPeriodExpired,
    SocialAccessTokenExpired,
    SocialLoginIdentifierNotFound,
    SocialUserExists,
    TokenAuthenticationFailed,
    UsernameAlreadyTaken,
    UserTagUpdateRestricted,
)

from .models import (
    ConfirmEmail,
    SocialLoginIdentifier,
    User,
)
from .social_auth import AppleAuthModule, GoogleAuthModule, SocialAuthModule


class CustomerAccountHandler:
    """
    Account-related helper for general users (supporters).

    By default, all accounts have customer permissions.
    """

    def __init__(self, **kwargs) -> None:
        self.user: User | None = kwargs.get("user", None)
        self.email: str | None = kwargs.get("email", None)
        self.password: str | None = kwargs.get("password", None)
        self.profile_name: str | None = kwargs.get("profile_name", None)
        self.username: str | None = kwargs.get("username", None)
        self.bio: str = kwargs.get("bio", "")

    @transaction.atomic
    def email_signup(self) -> tuple[User, dict]:
        email = self.email.lower() if self.email else None
        username = self.username.lower() if self.username else None

        try:
            user = User.objects.create_user(
                email=email,
                password=self.password,
                profile_name=self.profile_name,
                username=username,
                bio=self.bio,
            )
        except IntegrityError:
            raise AlreadyEnrolledEmail()

        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def login_id_duplicate_check(self) -> str:
        # TODO - Decide how withdrawn or dormant accounts should be handled.
        # Ensure email is lowercase and check case-insensitively
        email = self.email.lower() if self.email else None
        if User.objects.filter(login_id__iexact=email).exists():
            return LoginIdDuplicateCheckResultChoices.duplicated
        else:
            return LoginIdDuplicateCheckResultChoices.unique

    def login(self) -> tuple[User, dict]:
        user = self._authenticate()
        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def update_profile(self, **kwargs) -> User:
        # Format fields for update
        if "email" in kwargs and kwargs["email"]:
            kwargs["email"] = kwargs["email"].lower()

        if "username" in kwargs and kwargs["username"]:
            kwargs["username"] = kwargs["username"].lower()

        User.objects.filter(id=self.user.id).update(**kwargs)

        self.user.refresh_from_db()
        return self.user

    def update_username(self, username: str) -> User:
        """
        Change user's profile tag (username).
        It can be changed only once within 31 days.

        Args:
            username: Profile tag to change to

        Returns:
            User: Updated user object

        Raises:
            UserTagUpdateRestricted: Raised when changing tag again within 31 days
        """
        # Ensure username is lowercase for consistency
        if username:
            username = username.lower()

        # Check if username is available (not used by other users)
        if (
            User.objects.filter(username__iexact=username)
            .exclude(id=self.user.id)
            .exists()
        ):
            raise UsernameAlreadyTaken()

        # Check if user has changed tag in the last 31 days
        thirty_one_days_ago = timezone.now() - timedelta(days=31)
        if (
            self.user.username_changed_at
            and self.user.username_changed_at > thirty_one_days_ago
        ):
            raise UserTagUpdateRestricted()

        old_username = self.user.username

        # Update the username and record the change time, then cascade to related content
        with transaction.atomic():
            # Update user model
            User.objects.filter(id=self.user.id).update(
                username=username, username_changed_at=timezone.now()
            )

            # Since username is accessed via cached_property in content models,
            # we don't need to update the actual content tables

            # However, we should invalidate any caches that might store the username separately
            # This is a good place to add cache invalidation if needed in the future

        # Refresh user from database
        self.user.refresh_from_db()
        return self.user

    def logout(self, token_value: str) -> None:
        self.user.authtoken_set.filter(token_key=token_value).delete()

    def reset_password(self, new_password: str, email: str | None = None, language: str = "ko") -> None:
        user = self.user
        if (not user or user.is_anonymous) and email:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                raise NotEnrolledEmail()

        if not user:
            raise NotEnrolledEmail()

        user.set_password(new_password)
        now = timezone.now()
        user.password_changed_at = now
        user.save()

    def _authenticate(self) -> User:
        """Authenticate user by email/password.

        If ``django.contrib.auth.authenticate`` fails (e.g. because the
        account is inactive), a secondary path checks the password manually
        and, if valid, attempts account recovery. This allows users whose
        account is marked for deletion to log back in within the 30-day
        recovery window.
        """
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

    def send_confirm_code(self, email: str, is_signup: bool = True, language: str = "ko") -> dict:
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

        # TODO: Re-enable email sending via EmailService when ready for production.

        return {
            "created_at": confirm_email.created,
            "expires_in_minutes": settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES,
        }

    def check_confirm_code(self, email: str, confirm_code: str) -> bool:
        """
        Verify the confirmation code for a given email address.

        Args:
            email: The email to verify
            confirm_code: The confirmation code to check

        Returns:
            bool: True if the code is valid and confirmed

        Raises:
            EmailVerificationCodeExpired: If the verification code has expired
            InvalidVerificationCode: If the code doesn't match
        """
        email = email.lower() if email else None

        email_confirmation = self._get_latest_confirmation(email)

        # In dev/local environments, accept 000000 as a bypass code
        if confirm_code == "000000" and settings.ENV in ["dev", "local"]:
            self._mark_confirmed(email_confirmation)
            return True

        # Regular validation — code must match
        if email_confirmation.confirm_code != confirm_code:
            raise InvalidVerificationCode()

        self._mark_confirmed(email_confirmation)
        return True

    @staticmethod
    def _get_latest_confirmation(email: str) -> ConfirmEmail:
        """Fetch the most recent confirmation record and validate it hasn't expired."""
        email_confirmation = (
            ConfirmEmail.objects.filter(email__iexact=email)
            .order_by("-created")
            .first()
        )

        if not email_confirmation:
            raise InvalidVerificationCode()

        expiry_time = email_confirmation.created + timedelta(
            minutes=settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
        )
        if timezone.now() > expiry_time:
            raise EmailVerificationCodeExpired()

        return email_confirmation

    @staticmethod
    def _mark_confirmed(email_confirmation: ConfirmEmail) -> None:
        """Mark a confirmation record as confirmed."""
        email_confirmation.is_confirmed = True
        email_confirmation.save()

    def _check_confirmed_email(self, email: str) -> bool:
        return ConfirmEmail.objects.filter(email=email, is_confirmed=True).exists()

    def force_login(self, email: str) -> tuple[User, dict]:
        user = User.objects.get(email=email)
        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    @transaction.atomic
    def delete_account(self) -> bool:
        """
        Process account deletion (withdrawal) with a 30-day recovery period.

        Deletion is not immediate; the account is deactivated for 30 days.
        The account can be recovered within that period.
        Deletion is finalized after 30 days.

        Returns:
            bool: True on successful deletion request

        Raises:
            ValueError: If no user is provided
        """
        if not self.user:
            raise ValueError("User information is required to delete an account")

        self.user.authtoken_set.all().delete()

        self.user.is_active = False
        self.user.deletion_requested_at = timezone.now()
        self.user.save()

        # TODO: Re-enable social login token withdrawal when ready.

        return True

    @transaction.atomic
    def recover_account(self) -> bool:
        """
        Recover an account marked for deletion (within 30 days).

        Returns:
            bool: True on successful recovery

        Raises:
            ValueError: If no user is provided
            AccountNotMarkedForDeletion: If the account is not marked for deletion
            RecoveryPeriodExpired: If the 30-day recovery period has expired
        """
        if not self.user:
            raise ValueError("User information is required to recover an account")

        # Check if the account is marked for deletion
        if not self.user.deletion_requested_at:
            raise AccountNotMarkedForDeletion()

        # Check if the recovery period (30 days) has expired
        thirty_days_ago = timezone.now() - timedelta(days=30)
        if self.user.deletion_requested_at < thirty_days_ago:
            raise RecoveryPeriodExpired()

        # Reactivate the account
        self.user.is_active = True
        self.user.deletion_requested_at = None
        self.user.save()

        return True


class SocialAuthHandler:
    def __init__(self, provider: str | None) -> None:
        self.provider = provider
        self.module: SocialAuthModule | None = self.get_module()

    def get_module(self) -> SocialAuthModule | None:
        if self.provider == SocialLoginProviderChoices.google:
            return GoogleAuthModule()
        elif self.provider == SocialLoginProviderChoices.apple:
            return AppleAuthModule()
        else:
            return None

    def check(self, access_token: str) -> tuple:
        """
        Validate social login information.

        Args:
            access_token: Access token issued by the social login provider

        Returns:
            Tuple of (social_uuid, email, is_new)

        Raises:
            TokenAuthenticationFailed: If token is invalid
        """
        if self.provider is None:
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
        elif email and User.objects.filter(email__iexact=email).exists():
            user = User.objects.get(email__iexact=email)
            social_login_identifier = SocialLoginIdentifier.objects.create(
                provider=self.provider,
                identifier=identifier,
                email=email,
                temp_access_token=access_token[:100],
                user=user,
            )
            return social_login_identifier.id, email, False
        else:
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
        social_uuid: str,
        access_token: str,
        profile_name: str,
        username: str,
        bio: str,
        **kwargs,
    ) -> tuple[User, dict]:
        if not SocialLoginIdentifier.objects.filter(id=social_uuid).exists():
            raise SocialLoginIdentifierNotFound()
        social_login_identifier = SocialLoginIdentifier.objects.get(id=social_uuid)
        if social_login_identifier.user is not None:
            raise SocialUserExists()
        if social_login_identifier.temp_access_token != access_token[:100]:
            raise SocialAccessTokenExpired()

        username = username.lower() if username else None

        try:
            user = User.objects.create_user(
                email=social_login_identifier.email.lower(),
                password=None,
                profile_name=profile_name,
                username=username,
                bio=bio,
            )
        except IntegrityError:
            raise AlreadyEnrolledEmail()

        social_login_identifier.user = user
        social_login_identifier.save()

        # TODO: Re-enable welcome email via EmailService when ready for production.

        token_value, expiry = CreateToken(user=user).create()
        return user, {"token_value": token_value, "expiry": expiry}

    def login(self, social_uuid: str, access_token: str) -> tuple[User, dict]:
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

    def withdrawal(self, social_login_identifier: SocialLoginIdentifier) -> None:
        self.module.withdrawal(social_login_identifier.identifier)
