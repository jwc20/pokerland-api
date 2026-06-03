from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from auth_tokens.utils import CreateToken
from utils.exceptions import InvalidLoginInfo

from ..factories import (
    CustomerFactory,
)
from ..models import Customer, hash_client_token


class CustomerEmailLoginAPIViewTest(TestCase):
    def test_success(self):
        customer = CustomerFactory(password=None)
        raw_password = "DummyPassword1!"
        customer.set_password(raw_password)
        customer.save()

        response = APIClient().post(
            reverse("user-login-email"),
            {
                "email": customer.email,
                "password": raw_password,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_user_data = response.json().get("user")
        self.assertEqual(response_user_data.get("email"), customer.email)
        self.assertFalse(response_user_data.get("is_staff"))

    def test_wrong_password(self):
        customer = CustomerFactory(password=None)
        raw_password = "DummyPassword1!"
        customer.set_password(raw_password)
        customer.save()
        wrong_password = f"wrong{raw_password}"

        response = APIClient().post(
            reverse("user-login-email"),
            {
                "email": customer.email,
                "password": wrong_password,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )

        self.assertEqual(response.status_code, InvalidLoginInfo.status_code)
        self.assertEqual(response.json().get("detail"), InvalidLoginInfo.default_detail)


class CustomerEmailSignupAPIViewTestCase(TestCase):
    def test_success(self):
        email = "test1@dummy.com"
        password = "RawPassword1!"
        profile_name = "John Doe"
        username = "@honggildong33"
        bio = ""
        response = APIClient().post(
            reverse("user-signup-email"),
            {
                "email": email,
                "password": password,
                "profile_name": profile_name,
                "username": username,
                "bio": bio,
            },
            format="json",
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertIsNotNone(response_data.get("user", None))
        self.assertIsNotNone(response_data.get("token_info", None))
        client_token = response_data.get("client_token")
        self.assertIsNotNone(client_token)
        customer = Customer.objects.get(email=email)
        self.assertEqual(customer.username, username)
        self.assertEqual(customer.profile_name, profile_name)
        self.assertEqual(customer.client_token_hash, hash_client_token(client_token))
        self.assertNotEqual(customer.client_token_hash, client_token)
        self.assertFalse(customer.is_staff)


class MyProfileAPIViewTestCase(TestCase):
    def test_success(self):
        user = CustomerFactory()
        token_value, _ = CreateToken(user=user).create()
        response = APIClient().get(
            reverse("user-my-profile"),
            format="json",
            HTTP_TOKEN=token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_user_data = response.json()
        self.assertEqual(response_user_data.get("email"), user.email)


class MyProfileUpdateAPIViewTestCase(TestCase):
    def test_success(self):
        user = CustomerFactory()
        profile_name = "Updated Name"
        username = "@after_change"
        token_value, _ = CreateToken(user=user).create()
        response = APIClient().patch(
            reverse("user-my-profile-update"),
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
        self.customer = CustomerFactory()
        self.token_value, _ = CreateToken(user=self.customer).create()
        self.client = APIClient()

    def test_request_account_deletion(self):
        response = self.client.post(
            reverse("user-delete-account"),
            {},
            HTTP_TOKEN=self.token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.deletion_requested_at)

    def test_account_recovery_success(self):
        self.customer.is_active = False
        self.customer.deletion_requested_at = timezone.now()
        self.customer.save()

        new_token_value, _ = CreateToken(user=self.customer).create()

        response = self.client.post(
            reverse("user-recover-account"),
            {},
            HTTP_TOKEN=new_token_value,
            HTTP_app_version="1.0.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.deletion_requested_at)

    def test_account_recovery_expired(self):
        self.customer.is_active = False
        self.customer.deletion_requested_at = timezone.now() - timedelta(days=31)
        self.customer.save()

        new_token_value, _ = CreateToken(user=self.customer).create()

        response = self.client.post(
            reverse("user-recover-account"),
            {},
            HTTP_TOKEN=new_token_value,
            HTTP_app_version="1.0.1",
        )
        # Token is not issued when is_active is False
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertIsNotNone(self.customer.deletion_requested_at)
