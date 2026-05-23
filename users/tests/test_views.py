from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from auth_tokens.utils import CreateToken
from utils.exceptions import InvalidLoginInfo, RecoveryPeriodExpired

from ..factories import (
    CustomerFactory,
)
from ..models import Customer


class CustomerEmailLoginAPIViewTest(TestCase):
    def test_정상(self):
        # 데이터 생성
        customer = CustomerFactory()
        raw_password = "DummyPassword1!"
        customer.set_password(raw_password)
        customer.save()

        # 호출
        response = APIClient().post(
            "/user/login/email",
            {
                "email": customer.email,
                "password": raw_password,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )

        # 검증
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_user_data = response.json().get("user")
        self.assertEqual(response_user_data.get("email"), customer.email)
        self.assertFalse(response_user_data.get("is_creator"))
        self.assertFalse(response_user_data.get("is_staff"))

    def test_비밀번호_틀림(self):
        # 데이터 생성
        customer = CustomerFactory()
        raw_password = "DummyPassword1!"
        customer.set_password(raw_password)
        customer.save()
        wrong_password = f"wrong{raw_password}"

        # 호출
        response = APIClient().post(
            "/user/login/email",
            {
                "email": customer.email,
                "password": wrong_password,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )

        # 검증
        self.assertEqual(response.status_code, InvalidLoginInfo.status_code)
        self.assertEqual(response.json().get("detail"), InvalidLoginInfo.default_detail)


class CustomerEmailSignupAPIViewTestCase(TestCase):
    def test_정상(self):
        email = "test1@dummy.com"
        password = "RawPassword1!"
        profile_name = "홍길동"
        username = "@honggildong33"
        bio = ""
        is_ad_agreed = True
        is_ad_night_agreed = True
        response = APIClient().post(
            "/user/signup/email",
            {
                "email": email,
                "password": password,
                "profile_name": profile_name,
                "username": username,
                "bio": bio,
                "is_ad_agreed": is_ad_agreed,
                "is_ad_night_agreed": is_ad_night_agreed,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertIsNotNone(response_data.get("user", None))
        self.assertIsNotNone(response_data.get("token_info", None))
        customer = Customer.objects.get(email=email)
        self.assertEqual(customer.username, username)
        self.assertEqual(customer.profile_name, profile_name)

        self.assertFalse(customer.is_creator)
        self.assertFalse(customer.is_staff)

        self.assertEqual(customer.ad_agreement.is_agreed, is_ad_agreed)
        self.assertEqual(customer.ad_night_agreement.is_agreed, is_ad_agreed)


class MyProfileAPIViewTestCase(TestCase):
    def test_정상(self):
        user = CustomerFactory()
        token_value, _ = CreateToken(user=user).create()
        with self.assertNumQueries(8):
            response = APIClient().get(
                f"/user/my_profile",
                format="json",
                HTTP_TOKEN=token_value,
                HTTP_app_version="1.0.1",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_user_data = response.json()


class MyProfileUpdateAPIViewTestCase(TestCase):
    def test_정상(self):
        user = CustomerFactory()
        profile_name = "변경후 이름"
        username = "@after_change"
        token_value, _ = CreateToken(user=user).create()
        response = APIClient().post(
            f"/user/my_profile/update",
            {
                "profile_name": profile_name,
                "username": username,
            },
            format="json",
            HTTP_TOKEN=token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.profile_name, profile_name)
        self.assertEqual(user.username, username)


class AccountDeletionRecoveryTest(TestCase):
    def setUp(self):
        # 테스트 사용자 생성
        self.customer = CustomerFactory()
        self.token_value, _ = CreateToken(user=self.customer).create()
        self.client = APIClient()

    def test_계정_삭제_요청(self):
        # 계정 삭제 요청
        response = self.client.post(
            "/user/delete_account",
            {},
            HTTP_TOKEN=self.token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 계정과 관련 데이터 확인
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.deletion_requested_at)

        # 광고 동의 확인
        self.ad_agreement.refresh_from_db()
        self.assertFalse(self.ad_agreement.is_agreed)

        # 야간 광고 동의 확인
        self.ad_night_agreement.refresh_from_db()
        self.assertFalse(self.ad_night_agreement.is_agreed)

        # 크리에이터 링크 확인
        self.creator_link.refresh_from_db()
        self.assertTrue(self.creator_link.is_deleted)

    def test_계정_복구_성공(self):
        # 먼저 계정 삭제
        self.customer.is_active = False
        self.customer.deletion_requested_at = timezone.now()
        self.customer.save()

        # 새 토큰 생성 (삭제 시 기존 토큰이 모두 삭제됨)
        new_token_value, _ = CreateToken(user=self.customer).create()

        # 계정 복구 요청
        response = self.client.post(
            "/user/recover_account",
            {},
            HTTP_TOKEN=new_token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 계정 상태 확인
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.deletion_requested_at)

    def test_계정_복구_만료(self):
        # 31일 전에 삭제된 계정 설정
        self.customer.is_active = False
        self.customer.deletion_requested_at = timezone.now() - timedelta(days=31)
        self.customer.save()

        # 새 토큰 생성
        new_token_value, _ = CreateToken(user=self.customer).create()

        # 계정 복구 요청 (실패해야 함)
        response = self.client.post(
            "/user/recover_account",
            {},
            HTTP_TOKEN=new_token_value,
            HTTP_app_version="1.0.1",
        )
        # is_active가 false이면 token이 생성되지 않음
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # self.assertEqual(response.json()["detail"], "recovery_period_expired")

        # 계정 상태 확인 (여전히 비활성 상태여야 함)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.deletion_requested_at)
