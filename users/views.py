from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from auth_tokens.auth import StrictTokenAuthentication
from utils.paginations import ApiPageNumberPagination
from users.serializers import (
    UserMyProfileResponseSerializer,
    UserEmailSignupSerializer,
    UserMyProfileUpdateSerializer,
    UserEmailSendConfirmCodeSerializer,
    UserEmailSendConfirmCodeResponseSerializer,
    UserEmailCheckConfirmCodeSerializer,
    UserEmailCheckConfirmCodeResponseSerializer,
    CreatorProfileResponseSerializer,
    UserFindPwEmailSendConfirmCodeSerializer,
    UserFindPwEmailCheckConfirmCodeSerializer,
    UserFindPwEmailCheckConfirmCodeResponseSerializer,
    UserEmailResetPwSerializer,
    UserEmailAvailabilitySerializer,
    UserEmailAvailabilityResponseSerializer,
    UserTagAvailabilitySerializer,
    UserTagAvailabilityResponseSerializer,
    UserTagUpdateSerializer,
    UserDeleteAccountSerializer,
    UserRecoverAccountSerializer,
    UserSocialCheckRequestSerializer,
    UserSocialCheckResponseSerializer,
    UserSocialSignupSerializer,
    UserSocialSigninSerializer,
    UserBlockResponseSerializer,
    BlockedUsersResponseSerializer,
    PaginatedBlockedUsersResponseSerializer,
)
from utils.commons import EmptySerializer
from utils.custom_swaggers.commons import (
    custom_swagger_auto_schema,
    get_swagger_response_dict,
)
from utils.exceptions import (
    InvalidLoginInfo,
    AlreadyEnrolledEmail,
    NotEnrolledEmail,
    TokenAuthenticationFailed,
    EmailVerificationCodeExpired,
    EmailVerificationRateLimited,
    InvalidVerificationCode,
    AccountNotMarkedForDeletion,
    RecoveryPeriodExpired,
    SocialLoginIdentifierNotFound,
    SocialUserExists,
    SocialAccessTokenExpired,
    UserDoesNotExist,
    CannotBlockYourself,
    UserTagUpdateRestricted,
)
from utils.permissions import ApiPermission
from .serializers import (
    UserEmailLoginSerializer,
    UserSignupLoginResponseSerializer,
)
from .utils import CustomerAccountHandler, SocialAuthHandler, UserBlockHandler

User = get_user_model()


class UserEmailLoginAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailLoginSerializer

    @custom_swagger_auto_schema(
        operation_summary="이메일을 통한 로그인",
        operation_description="""
        ### 인증 및 권한
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
        operation_summary="이메일을 통한 회원가입(이메일 인증 필요)",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            api_exceptions=[
                AlreadyEnrolledEmail,
            ],
            success_response={status.HTTP_200_OK: UserSignupLoginResponseSerializer},
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Get language from request (set by LanguageMiddleware)
        language = getattr(request, "language", "ko")
        user, token_info = CustomerAccountHandler(
            **serializer.validated_data
        ).email_signup(language=language)
        return Response(
            status=status.HTTP_200_OK,
            data=UserSignupLoginResponseSerializer(
                {
                    "user": user,
                    "token_info": token_info,
                }
            ).data,
        )


class MyProfileAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]

    @custom_swagger_auto_schema(
        operation_summary="고객 본인 정보 보기",
        operation_description="""
            ### 인증 및 권한
            1. api-key
            2. Token (로그인 필요)
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


# TODO - 테스트 필요
class MyProfileUpdateAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = UserMyProfileUpdateSerializer

    @custom_swagger_auto_schema(
        operation_summary="고객 본인 정보 수정",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def post(self, request, *args, **kwargs):
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
        operation_summary="로그아웃",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: EmptySerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def post(self, request, *args, **kwargs):
        user = request.user
        # TODO - 아래 로직 모듈화 필요
        token_value = request.META.get(
            f"HTTP_{settings.AUTH_TOKEN_SETTING['AUTH_HEADER_PREFIX'].upper()}", None
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
        operation_summary="제출한 이메일로 인증 코드 전송",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        ### 참고 사항
        전송된 이메일 인증코드는 {0}분 이내에 입력해야 합니다.
        10분 이내에 최대 3회까지만 요청할 수 있습니다.
        """.format(
            settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
        ),
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
        operation_summary="인증 코드 확인 prod 이외 환경에서는 무조건 `000000`",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        ### 참고 사항
        이메일 인증코드는 {0}분 이내에 입력해야 합니다.
        """.format(
            settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
        ),
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


class CreatorProfileAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]

    @custom_swagger_auto_schema(
        operation_summary="고객 본인 정보 보기",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: CreatorProfileResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def get(self, request, *args, **kwargs):
        user_tag = kwargs["user_tag"]

        creator = User.objects.get(user_tag__iexact=user_tag, is_creator=True)
        return Response(
            status=status.HTTP_200_OK,
            data=CreatorProfileResponseSerializer(creator).data,
        )


class UserFindPwEmailSendConfirmCodeAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserFindPwEmailSendConfirmCodeSerializer

    @custom_swagger_auto_schema(
        operation_summary="비밀번호 찾기 이메일로 인증 코드 전송",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        ### 참고 사항
        전송된 이메일 인증코드는 {0}분 이내에 입력해야 합니다.
        10분 이내에 최대 3회까지만 요청할 수 있습니다.
        """.format(
            settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
        ),
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
        operation_summary="비밀번호 찾기 인증 코드 확인 prod 이외 환경에서는 무조건 `000000`",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        ### 참고 사항
        이메일 인증코드는 {0}분 이내에 입력해야 합니다.
        """.format(
            settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES
        ),
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
                {"is_confirmed": is_confirmed, "user": user, "token_info": token_info}
            ).data,
        )


class UserEmailResetPwAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserEmailResetPwSerializer

    @custom_swagger_auto_schema(
        operation_summary="비밀번호 변경",
        operation_description="""
        ### 인증 및 권한
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
        operation_summary="이메일 사용 가능 여부 확인",
        operation_description="""
        ### 인증 및 권한
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
        operation_summary="유저 태그 사용 가능 여부 확인",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: UserTagAvailabilityResponseSerializer
            },
        ),
        security=[{"api-key": {"type": "apiKey", "name": "api-key", "in": "header"}}],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get the user_tag from the request and ensure proper format
        user_tag = serializer.validated_data["user_tag"].lower()

        # Case-insensitive check to ensure uniqueness
        is_available = not User.objects.filter(user_tag__iexact=user_tag).exists()

        return Response(
            status=status.HTTP_200_OK,
            data=UserTagAvailabilityResponseSerializer(
                {"is_available": is_available}
            ).data,
        )


class UserDeleteAccountAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = UserDeleteAccountSerializer

    @custom_swagger_auto_schema(
        operation_summary="계정 삭제(탈퇴)",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        ### 참고 사항
        계정 삭제 시 30일의 복구 기간이 제공됩니다.
        30일 이내에 계정 복구가 가능하며, 이후에는 영구 삭제됩니다.
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
    #     operation_summary="계정 삭제(탈퇴) 확인 페이지",
    #     operation_description="""
    #     ### 인증 및 권한
    #     1. api-key
    #     2. Token (로그인 필요)
    #     ---
    #     ### 참고 사항
    #     계정 삭제 확인을 위한 정보를 조회합니다.
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
    serializer_class = UserRecoverAccountSerializer

    @custom_swagger_auto_schema(
        operation_summary="계정 복구",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        ### 참고 사항
        삭제 요청된 계정은 30일 이내에 복구할 수 있습니다.
        30일이 지난 후에는 계정을 복구할 수 없습니다.
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
    serializer_class = UserTagUpdateSerializer

    @custom_swagger_auto_schema(
        operation_summary="프로필 태그 변경",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        ### 참고 사항
        프로필 태그는 31일에 한 번만 변경할 수 있습니다.
        프로필 태그 변경 시 사용자의 모든 컨텐츠, 게시글, 댓글 등에 변경사항이 자동으로 반영됩니다.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[
                TokenAuthenticationFailed,
                UserTagUpdateRestricted,
                AlreadyEnrolledEmail,
            ],
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = CustomerAccountHandler(user=request.user).update_user_tag(
            serializer.validated_data["user_tag"]
        )

        return Response(
            status=status.HTTP_200_OK,
            data=UserMyProfileResponseSerializer(user).data,
        )


class UserProfileAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]

    @custom_swagger_auto_schema(
        operation_summary="유저 프로필 조회",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserMyProfileResponseSerializer},
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def get(self, request, *args, **kwargs):
        user_tag = kwargs["user_tag"]

        creator = User.objects.get(user_tag__iexact=user_tag)
        return Response(
            status=status.HTTP_200_OK,
            data=UserMyProfileResponseSerializer(creator).data,
        )


class UserSocialCheckAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserSocialCheckRequestSerializer

    @custom_swagger_auto_schema(
        operation_summary="소셜 로그인 유효성 검사",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        access_token이 유효하지않으면 TokenAuthenticationFailed 에러를 반환합니다
        social_uuid는 회원가입과 로그인에 사용되는 고유 식별자입니다.
        is_new가 True이면 소셜 로그인 신규 가입 프로세스를 진행합니다.
        is_new가 False이면 소셜 로그인 기존 가입 프로세스를 진행합니다.
        
        google은 queryParameter로 오는 code, apple은 identityToken을 access_token으로 사용합니다.
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
                {"social_uuid": social_uuid, "email": email, "is_new": is_new}
            ).data,
        )


class UserSocialSignupAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserSocialSignupSerializer

    @custom_swagger_auto_schema(
        operation_summary="소셜 로그인 신규 가입",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        이메일 신규 가입과 거의 동일한 로직을 사용합니다.
        이메일과 비밀번호 대신 social_uuid와 access_token을 사용합니다.
        해당 이메일이 이미 다른 계정으로 등록되어 있으면 AlreadyEnrolledEmail 에러가 발생합니다.
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
        user, token_info = social_auth_handler.create_user(
            language=language, **serializer.validated_data
        )

        return Response(
            status=status.HTTP_200_OK,
            data=UserSignupLoginResponseSerializer(
                {
                    "user": user,
                    "token_info": token_info,
                }
            ).data,
        )


class UserSocialSigninAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = []
    serializer_class = UserSocialSigninSerializer

    @custom_swagger_auto_schema(
        operation_summary="소셜 로그인(기존 회원)",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        ---
        검증된 소셜 로그인 정보를 바탕으로 로그인합니다.
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


class UserBlockAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = EmptySerializer

    @custom_swagger_auto_schema(
        operation_summary="사용자 차단",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        특정 사용자를 차단합니다.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: UserBlockResponseSerializer},
            api_exceptions=[
                UserDoesNotExist,
                CannotBlockYourself,
                TokenAuthenticationFailed,
            ],
        ),
    )
    def post(self, request, user_tag, *args, **kwargs):
        user = request.user
        block_handler = UserBlockHandler(user=user)

        user_block = block_handler.block_user(user_tag=user_tag)

        return Response(
            status=status.HTTP_200_OK,
            data=UserBlockResponseSerializer(user_block).data,
        )


class UserUnblockAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = EmptySerializer

    @custom_swagger_auto_schema(
        operation_summary="사용자 차단 해제",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        특정 사용자의 차단을 해제합니다.
        """,
        responses=get_swagger_response_dict(
            success_response={status.HTTP_200_OK: EmptySerializer},
            api_exceptions=[UserDoesNotExist, TokenAuthenticationFailed],
        ),
    )
    def post(self, request, user_tag, *args, **kwargs):
        user = request.user
        block_handler = UserBlockHandler(user=user)

        block_handler.unblock_user(user_tag=user_tag)

        return Response(
            status=status.HTTP_200_OK,
        )


class BlockedUsersAPIView(GenericAPIView):
    permission_classes = [ApiPermission]
    authentication_classes = [StrictTokenAuthentication]
    serializer_class = EmptySerializer
    pagination_class = ApiPageNumberPagination
    page_size = settings.DEFAULT_PAGE_SIZE  # Use default page size from settings

    @custom_swagger_auto_schema(
        operation_summary="차단한 사용자 목록 조회",
        operation_description="""
        ### 인증 및 권한
        1. api-key
        2. Token (로그인 필요)
        ---
        사용자가 차단한 사용자 목록을 조회합니다.
        """,
        responses=get_swagger_response_dict(
            success_response={
                status.HTTP_200_OK: PaginatedBlockedUsersResponseSerializer
            },
            api_exceptions=[TokenAuthenticationFailed],
        ),
    )
    def get(self, request, *args, **kwargs):
        user = request.user
        block_handler = UserBlockHandler(user=user)

        blocked_users = block_handler.get_blocked_users().order_by("-created")

        page = self.paginate_queryset(blocked_users)
        return self.paginator.get_paginated_response(
            BlockedUsersResponseSerializer(page, many=True).data
        )
