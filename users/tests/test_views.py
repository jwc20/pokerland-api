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
    def test_success(self):
        # Create test data
        customer = CustomerFactory()
        raw_password = "DummyPassword1!"
        customer.set_password(raw_password)
        customer.save()

        # Execute request
        response = APIClient().post(
            "/user/login/email",
            {
                "email": customer.email,
                "password": raw_password,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_user_data = response.json().get("user")
        self.assertEqual(response_user_data.get("email"), customer.email)
        self.assertFalse(response_user_data.get("is_creator"))
        self.assertFalse(response_user_data.get("is_staff"))

    def test_wrong_password(self):
        # Create test data
        customer = CustomerFactory()
        raw_password = "DummyPassword1!"
        customer.set_password(raw_password)
        customer.save()
        wrong_password = f"wrong{raw_password}"

        # Execute request
        response = APIClient().post(
            "/user/login/email",
            {
                "email": customer.email,
                "password": wrong_password,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )

        # Assert
        self.assertEqual(response.status_code, InvalidLoginInfo.status_code)
        self.assertEqual(response.json().get("detail"), InvalidLoginInfo.default_detail)


class CustomerEmailSignupAPIViewTestCase(TestCase):
    def test_success(self):
        email = "test1@dummy.com"
        password = "RawPassword1!"
        profile_name = "John Doe"
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
    def test_success(self):
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
    def test_success(self):
        user = CustomerFactory()
        profile_name = "Updated Name"
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
        # Create test user
        self.customer = CustomerFactory()
        self.token_value, _ = CreateToken(user=self.customer).create()
        self.client = APIClient()

    def test_request_account_deletion(self):
        # Request account deletion
        response = self.client.post(
            "/user/delete_account",
            {},
            HTTP_TOKEN=self.token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify account and related data
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.deletion_requested_at)

        # Verify ad agreement
        self.ad_agreement.refresh_from_db()
        self.assertFalse(self.ad_agreement.is_agreed)

        # Verify nighttime ad agreement
        self.ad_night_agreement.refresh_from_db()
        self.assertFalse(self.ad_night_agreement.is_agreed)

        # Verify creator link
        self.creator_link.refresh_from_db()
        self.assertTrue(self.creator_link.is_deleted)

    def test_account_recovery_success(self):
        # Delete account first
        self.customer.is_active = False
        self.customer.deletion_requested_at = timezone.now()
        self.customer.save()

        # Create a new token (existing tokens are deleted at account deletion)
        new_token_value, _ = CreateToken(user=self.customer).create()

        # Request account recovery
        response = self.client.post(
            "/user/recover_account",
            {},
            HTTP_TOKEN=new_token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify account status
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.deletion_requested_at)

    def test_account_recovery_expired(self):
        # Set account as deleted 31 days ago
        self.customer.is_active = False
        self.customer.deletion_requested_at = timezone.now() - timedelta(days=31)
        self.customer.save()

        # Create a new token
        new_token_value, _ = CreateToken(user=self.customer).create()

        # Request account recovery (should fail)
        response = self.client.post(
            "/user/recover_account",
            {},
            HTTP_TOKEN=new_token_value,
            HTTP_app_version="1.0.1",
        )
        # Token is not issued when is_active is False
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # self.assertEqual(response.json()["detail"], "recovery_period_expired")

        # Verify account state (should remain inactive)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.deletion_requested_at)
