from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from auth_tokens.auth import StrictTokenAuthentication
from users.serializers import (
    UserEmailAvailabilityResponseSerializer,
    UserEmailAvailabilitySerializer,
    UserEmailCheckConfirmCodeResponseSerializer,
    UserEmailCheckConfirmCodeSerializer,
    UserEmailResetPwSerializer,
    UserEmailSendConfirmCodeResponseSerializer,
    UserEmailSendConfirmCodeSerializer,
    UserEmailSignupSerializer,
    UserFindPwEmailCheckConfirmCodeResponseSerializer,
    UserFindPwEmailCheckConfirmCodeSerializer,
    UserFindPwEmailSendConfirmCodeSerializer,
    UserMyProfileResponseSerializer,
    UserMyProfileUpdateSerializer,
    UsernameAvailabilityResponseSerializer,
    UsernameUpdateSerializer,
    UserSocialCheckRequestSerializer,
    UserSocialCheckResponseSerializer,
    UserSocialSigninSerializer,
    UserSocialSignupSerializer,
    UserTagAvailabilitySerializer,
)
from utils.commons import EmptySerializer
from utils.custom_swaggers.commons import (
    custom_swagger_auto_schema,
    get_swagger_response_dict,
)
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
from utils.permissions import ApiPermission

from .serializers import (
    UserEmailLoginSerializer,
    UserSignupLoginResponseSerializer,
)
from .utils import CustomerAccountHandler, SocialAuthHandler

User = get_user_model()


SWAGGER_TAG_AUTH_EMAIL = ["Users - Email Auth"]
SWAGGER_TAG_EMAIL_VERIFICATION = ["Users - Email Verification"]
SWAGGER_TAG_PASSWORD = ["Users - Password"]
SWAGGER_TAG_PROFILE = ["Users - Profile"]
SWAGGER_TAG_ACCOUNT = ["Users - Account"]
SWAGGER_TAG_USERNAME = ["Users - Username / Tag"]
SWAGGER_TAG_SOCIAL_AUTH = ["Users - Social Auth"]


class UserEmailLoginAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailLoginSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_AUTH_EMAIL,
        operation_id="user_email_login",
        operation_summary="Login with email",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            api_exceptions=[
                InvalidLoginInfo,
            ],
            success_response={status.HTTP_200_OK: UserSignupLoginResponseSerializer},
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, token_info = CustomerAccountHandler(**serializer.validated_data).login()
        return Response(
            status=status.HTTP_200_OK,
            data=UserSignupLoginResponseSerializer(
                {
                    "user": user,
                    "token_info": token_info,
                }
            ).data,
        )


class UserEmailSignupAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailSignupSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_AUTH_EMAIL,
        operation_id="user_email_signup",
        operation_summary="Sign up with email (email verification required)",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            api_exceptions=[
                AlreadyEnrolledEmail,
            ],
            success_response={status.HTTP_201_CREATED: UserSignupLoginResponseSerializer},
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, token_info, client_token = CustomerAccountHandler(
            **serializer.validated_data
        ).email_signup()
        return Response(
            status=status.HTTP_201_CREATED,
            data=UserSignupLoginResponseSerializer(
                {
                    "user": user,
                    "token_info": token_info,
                    "client_token": client_token,
                }
            ).data,
        )


class MyProfileAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_PROFILE,
        operation_id="user_my_profile_get",
        operation_summary="Get my profile",
        operation_description="""
            ### Authentication and Authorization
            1. api-key
            2. Token (login required)
            ---
            """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def get(self, request):
        return Response(
            status=status.HTTP_200_OK,
            data=UserMyProfileResponseSerializer(request.user).data,
        )


# TODO - Add tests
class MyProfileUpdateAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = UserMyProfileUpdateSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_PROFILE,
        operation_id="user_my_profile_update",
        operation_summary="Update my profile",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = CustomerAccountHandler(user=request.user).update_profile(
            **serializer.validated_data
        )
        return Response(
            status=status.HTTP_200_OK,
            data=UserMyProfileResponseSerializer(user).data,
        )


class UserLogoutAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = EmptySerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_AUTH_EMAIL,
        operation_id="user_logout",
        operation_summary="Logout",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: EmptySerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def post(self, request, *args, **kwargs):
        user = request.user
        # TODO - Extract the logic below into a reusable module.
        token_value = request.META.get(
            f"HTTP_{settings.AUTH_TOKEN_SETTING['AUTH_HEADER_PREFIX'].upper()}",
            None,
        )
        CustomerAccountHandler(user=user).logout(token_value)
        return Response(
            status=status.HTTP_200_OK,
        )


class UserEmailSendConfirmCodeAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailSendConfirmCodeSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_EMAIL_VERIFICATION,
        operation_id="user_signup_email_send_confirm_code",
        operation_summary="Send verification code to submitted email",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        ### Notes
        The emailed verification code must be entered within {0} minutes.
        You can request it up to 3 times within 10 minutes.
        """.format(settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES),
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UserEmailSendConfirmCodeResponseSerializer
            },
            api_exceptions=[
                AlreadyEnrolledEmail,
                EmailVerificationRateLimited,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get language from request (set by LanguageMiddleware)
        language = getattr(request, "language", "ko")

        result = CustomerAccountHandler().send_confirm_code(
            email=serializer.validated_data["email"],
            language=language,
        )
        return Response(
            status=status.HTTP_200_OK,
            data=UserEmailSendConfirmCodeResponseSerializer(result).data,
        )


class UserEmailCheckConfirmCodeAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailCheckConfirmCodeSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_EMAIL_VERIFICATION,
        operation_id="user_signup_email_check_confirm_code",
        operation_summary="Verify code (always `000000` in non-prod environments)",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        ### Notes
        The email verification code must be entered within {0} minutes.
        """.format(settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES),
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UserEmailCheckConfirmCodeResponseSerializer
            },
            api_exceptions=[
                AlreadyEnrolledEmail,
                EmailVerificationCodeExpired,
                InvalidVerificationCode,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_confirmed = CustomerAccountHandler().check_confirm_code(
            **serializer.validated_data,
        )
        return Response(
            status=status.HTTP_200_OK,
            data=UserEmailCheckConfirmCodeResponseSerializer(
                {"is_confirmed": is_confirmed}
            ).data,
        )


class UserFindPwEmailSendConfirmCodeAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserFindPwEmailSendConfirmCodeSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_PASSWORD,
        operation_id="user_find_pw_send_confirm_code",
        operation_summary="Send verification code for password reset",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        ### Notes
        The emailed verification code must be entered within {0} minutes.
        You can request it up to 3 times within 10 minutes.
        """.format(settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES),
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UserEmailSendConfirmCodeResponseSerializer
            },
            api_exceptions=[
                NotEnrolledEmail,
                EmailVerificationRateLimited,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get language from request (set by LanguageMiddleware)
        language = getattr(request, "language", "ko")

        result = CustomerAccountHandler().send_confirm_code(
            email=serializer.validated_data["email"],
            is_signup=False,
            language=language,
        )
        return Response(
            status=status.HTTP_200_OK,
            data=UserEmailSendConfirmCodeResponseSerializer(result).data,
        )


class UserFindPwEmailCheckConfirmCodeAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserFindPwEmailCheckConfirmCodeSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_PASSWORD,
        operation_id="user_find_pw_check_confirm_code",
        operation_summary="Verify password-reset code (always `000000` in non-prod)",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        ### Notes
        The email verification code must be entered within {0} minutes.
        """.format(settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES),
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UserFindPwEmailCheckConfirmCodeResponseSerializer
            },
            api_exceptions=[
                EmailVerificationCodeExpired,
                InvalidVerificationCode,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer_account_handler = CustomerAccountHandler()
        is_confirmed = customer_account_handler.check_confirm_code(
            **serializer.validated_data,
        )

        if is_confirmed:
            # Extract only the email from validated_data for force_login
            user, token_info = customer_account_handler.force_login(
                email=serializer.validated_data["email"]
            )
        else:
            user = None
            token_info = None

        return Response(
            status=status.HTTP_200_OK,
            data=UserFindPwEmailCheckConfirmCodeResponseSerializer(
                {
                    "is_confirmed": is_confirmed,
                    "user": user,
                    "token_info": token_info,
                }
            ).data,
        )


class UserEmailResetPwAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailResetPwSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_PASSWORD,
        operation_id="user_email_reset_pw",
        operation_summary="Reset password",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: EmptySerializer},
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Use user from token if authenticated, otherwise require email in payload
        user = request.user if request.user.is_authenticated else None
        if not user and "email" not in serializer.validated_data:
            return Response(
                {"error": "Email is required when not authenticated"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get language from request (set by LanguageMiddleware)
        language = getattr(request, "language", "ko")

        # Initialize handler with user if authenticated, otherwise will use email from payload
        handler = CustomerAccountHandler(user=request.user)
        handler.reset_password(**serializer.validated_data, language=language)

        return Response(
            status=status.HTTP_200_OK,
        )


class UserEmailAvailabilityAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailAvailabilitySerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_AUTH_EMAIL,
        operation_id="user_check_email_availability",
        operation_summary="Check email availability",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UserEmailAvailabilityResponseSerializer
            },
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Convert to lowercase for case-insensitive check
        email = serializer.validated_data["email"].lower()
        is_available = not User.objects.filter(email__iexact=email).exists()

        return Response(
            status=status.HTTP_200_OK,
            data=UserEmailAvailabilityResponseSerializer(
                {"is_available": is_available}
            ).data,
        )


class UserTagAvailabilityAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserTagAvailabilitySerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_USERNAME,
        operation_id="user_check_tag_availability",
        operation_summary="Check user tag availability",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UsernameAvailabilityResponseSerializer
            },
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get the username from the request and ensure proper format
        username = serializer.validated_data["username"].lower()

        # Case-insensitive check to ensure uniqueness
        is_available = not User.objects.filter(username__iexact=username).exists()

        return Response(
            status=status.HTTP_200_OK,
            data=UsernameAvailabilityResponseSerializer(
                {"is_available": is_available}
            ).data,
        )


class UserDeleteAccountAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = EmptySerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_ACCOUNT,
        operation_id="user_delete_account",
        operation_summary="Delete account (withdrawal)",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        ### Notes
        Deleting an account provides a 30-day recovery period.
        The account can be recovered within 30 days, then it is permanently deleted.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: EmptySerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Mark account for deletion with 30-day recovery period
        CustomerAccountHandler(user=request.user).delete_account()

        return Response(
            status=status.HTTP_200_OK,
        )

    #
    # @custom_swagger_auto_schema(
    #     tags=SWAGGER_TAG_ACCOUNT,
    #     operation_summary="Account deletion confirmation page",
    #     operation_description="""
    #     ### Authentication and Authorization
    #     1. api-key
    #     2. Token (login required)
    #     ---
    #     ### Notes
    #     Retrieves information for account deletion confirmation.
    #     """,
    #     responses=get_swagger_response_dict(
    #         success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
    #         api_exceptions=[TokenAuthenticationFailed],
    #     ),
    # )
    # def get(self, request, *args, **kwargs):
    #     # Return user profile to display account info before deletion
    #     return Response(
    #         status=status.HTTP_200_OK,
    #         data=UserMyProfileResponseSerializer(request.user).data,
    #     )


class UserRecoverAccountAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = EmptySerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_ACCOUNT,
        operation_id="user_recover_account",
        operation_summary="Recover account",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        ### Notes
        An account marked for deletion can be recovered within 30 days.
        After 30 days, it can no longer be recovered.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: EmptySerializer},
            api_exceptions=[
                TokenAuthenticationFailed,
                AccountNotMarkedForDeletion,
                RecoveryPeriodExpired,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Recover account within 30-day recovery period
        CustomerAccountHandler(user=request.user).recover_account()

        return Response(
            status=status.HTTP_200_OK,
        )


class UserTagUpdateAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = UsernameUpdateSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_USERNAME,
        operation_id="user_tag_update",
        operation_summary="Change profile tag",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        ### Notes
        Profile tag can be changed only once every 31 days.
        When changed, updates are reflected automatically across user content, posts, and comments.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[
                TokenAuthenticationFailed,
                UserTagUpdateRestricted,
                UsernameAlreadyTaken,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = CustomerAccountHandler(user=request.user).update_username(
            serializer.validated_data["username"]
        )

        return Response(
            status=status.HTTP_200_OK,
            data=UserMyProfileResponseSerializer(user).data,
        )


class UserProfileAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_PROFILE,
        operation_id="user_profile_get",
        operation_summary="Get user profile",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        2. Token (login required)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def get(self, request, *args, **kwargs):
        username = kwargs["username"]

        creator = User.objects.get(username__iexact=username)
        return Response(
            status=status.HTTP_200_OK,
            data=UserMyProfileResponseSerializer(creator).data,
        )


class UserSocialCheckAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserSocialCheckRequestSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_SOCIAL_AUTH,
        operation_id="user_social_check",
        operation_summary="Validate social login",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        Returns TokenAuthenticationFailed when access_token is invalid.
        social_uuid is a unique identifier used for signup and login.
        If is_new is True, proceed with social signup flow.
        If is_new is False, proceed with existing social sign-in flow.

        For Google, use the code received via query parameter.
        For Apple, use identityToken as access_token.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserSocialCheckResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed, AlreadyEnrolledEmail],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        social_uuid, email, is_new = SocialAuthHandler(
            serializer.validated_data["provider"]
        ).check(serializer.validated_data["access_token"])

        return Response(
            status=status.HTTP_200_OK,
            data=UserSocialCheckResponseSerializer(
                {
                    "social_uuid": social_uuid,
                    "email": email,
                    "is_new": is_new,
                }
            ).data,
        )


class UserSocialSignupAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserSocialSignupSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_SOCIAL_AUTH,
        operation_id="user_social_signup",
        operation_summary="Social login signup",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        Uses nearly the same flow as email signup.
        Uses social_uuid and access_token instead of email/password.
        Raises AlreadyEnrolledEmail if the email is already used by another account.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserSignupLoginResponseSerializer},
            api_exceptions=[
                TokenAuthenticationFailed,
                SocialLoginIdentifierNotFound,
                SocialUserExists,
                SocialAccessTokenExpired,
                AlreadyEnrolledEmail,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        language = getattr(request, "language", "ko")

        social_auth_handler = SocialAuthHandler(None)
        user, token_info, client_token = social_auth_handler.create_user(
            language=language,
            **serializer.validated_data,
        )

        return Response(
            status=status.HTTP_200_OK,
            data=UserSignupLoginResponseSerializer(
                {
                    "user": user,
                    "token_info": token_info,
                    "client_token": client_token,
                }
            ).data,
        )


class UserSocialSigninAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserSocialSigninSerializer

    @custom_swagger_auto_schema(
        tags=SWAGGER_TAG_SOCIAL_AUTH,
        operation_id="user_social_signin",
        operation_summary="Social login (existing user)",
        operation_description="""
        ### Authentication and Authorization
        1. api-key
        ---
        Signs in with validated social login information.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserSignupLoginResponseSerializer},
            api_exceptions=[
                SocialLoginIdentifierNotFound,
                NotEnrolledEmail,
                SocialAccessTokenExpired,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        social_auth_handler = SocialAuthHandler(None)
        user, token_info = social_auth_handler.login(**serializer.validated_data)

        return Response(
            status=status.HTTP_200_OK,
            data=UserSignupLoginResponseSerializer(
                {
                    "user": user,
                    "token_info": token_info,
                }
            ).data,
        )
