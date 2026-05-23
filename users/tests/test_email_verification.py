# import json
# from datetime import timedelta
# from unittest.mock import patch, MagicMock
#
# from django.conf import settings
# from django.test import TestCase
# from django.urls import reverse
# from django.utils import timezone
# from rest_framework import status
# from rest_framework.test import APIClient
#
# from users.models import User, ConfirmEmail
# from utils.exceptions import (
#     EmailVerificationCodeExpired,
#     EmailVerificationRateLimited,
#     InvalidVerificationCode,
# )
#
#
# class EmailVerificationTest(TestCase):
#     """Tests for email verification functionality"""
#
#     def setUp(self):
#         self.client = APIClient()
#         self.client.credentials(HTTP_API_KEY=settings.API_KEY)
#
#         # Create a test user for password reset tests
#         self.test_user = User.objects.create_user(
#             email="test@example.com",
#             password="TestPassword123!",
#             name="Test User",
#             user_tag="testuser",
#         )
#
#         # Setup URLs
#         self.signup_send_code_url = reverse("user-signup-email-send-confirm-code")
#         self.signup_check_code_url = reverse("user-signup-email-check-confirm-code")
#         self.pw_reset_send_code_url = reverse("user-find-pw-email-send-confirm-code")
#         self.pw_reset_check_code_url = reverse("user-find-pw-email-check-confirm-code")
#
#     @patch('utils.email_service.EmailService.send_template_email')
#     def test_signup_send_code_success(self, mock_send_email):
#         """Test sending verification code for signup - success case"""
#         mock_send_email.return_value = True
#
#         # Send verification code to new email
#         response = self.client.post(
#             self.signup_send_code_url,
#             {"email": "new_user@example.com"},
#             format="json"
#         )
#
#         # Check response
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertIn("expires_in_minutes", response.data)
#         self.assertIn("created_at", response.data)
#
#         # Check that code was created in DB
#         self.assertTrue(
#             ConfirmEmail.objects.filter(email="new_user@example.com").exists()
#         )
#
#         # Check that email was sent
#         mock_send_email.assert_called_once()
#
#     @patch('utils.email_service.EmailService.send_template_email')
#     def test_signup_send_code_existing_email(self, mock_send_email):
#         """Test sending verification code for signup - existing email case"""
#         # Try to send code to existing email
#         response = self.client.post(
#             self.signup_send_code_url,
#             {"email": "test@example.com"},  # Already exists
#             format="json"
#         )
#
#         # Should fail with AlreadyEnrolledEmail
#         self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(response.data["detail"], "already_enrolled_login_id")
#
#         # Email should not be sent
#         mock_send_email.assert_not_called()
#
#     @patch('utils.email_service.EmailService.send_template_email')
#     def test_signup_send_code_rate_limit(self, mock_send_email):
#         """Test rate limiting for sending verification codes"""
#         mock_send_email.return_value = True
#         email = "rate_limit@example.com"
#
#         # Create 3 recent confirmation codes
#         for i in range(3):
#             ConfirmEmail.objects.create(
#                 email=email,
#                 confirm_code="123456",
#                 created=timezone.now() - timedelta(minutes=5)
#             )
#
#         # Try to send another code (should be rate limited)
#         response = self.client.post(
#             self.signup_send_code_url,
#             {"email": email},
#             format="json"
#         )
#
#         # Should fail with rate limit error
#         self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
#         self.assertEqual(response.data["detail"], "email_verification_rate_limited")
#
#         # Email should not be sent
#         mock_send_email.assert_not_called()
#
#     def test_signup_check_code_success(self):
#         """Test checking verification code for signup - success case"""
#         email = "verify@example.com"
#         code = "123456"
#
#         # Create the confirmation record
#         ConfirmEmail.objects.create(
#             email=email,
#             confirm_code=code,
#             created=timezone.now()
#         )
#
#         # Check the code
#         response = self.client.post(
#             self.signup_check_code_url,
#             {"email": email, "confirm_code": code},
#             format="json"
#         )
#
#         # Should succeed
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertTrue(response.data["is_confirmed"])
#
#         # Record should be updated
#         conf_email = ConfirmEmail.objects.get(email=email)
#         self.assertTrue(conf_email.is_confirmed)
#
#     def test_signup_check_code_expired(self):
#         """Test checking expired verification code"""
#         email = "expired@example.com"
#         code = "123456"
#
#         # Use freezegun or mock timezone.now to set a specific time
#         expired_time = timezone.now() - timedelta(minutes=settings.EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES + 1)
#
#         with patch('django.utils.timezone.now') as mock_now:
#             # First return the expired time for creation
#             mock_now.return_value = expired_time
#
#             # Create the confirmation record with expired time
#             ConfirmEmail.objects.create(
#                 email=email,
#                 confirm_code=code,
#             )
#
#         response = self.client.post(
#             self.signup_check_code_url,
#             {"email": email, "confirm_code": code},
#             format="json"
#         )
#
#         # Should fail with expired error
#         self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(response.data["detail"], "email_verification_code_expired")
#
#     def test_signup_check_code_invalid(self):
#         """Test checking invalid verification code"""
#         email = "invalid@example.com"
#         real_code = "123456"
#         wrong_code = "654321"
#
#         # Create the confirmation record
#         ConfirmEmail.objects.create(
#             email=email,
#             confirm_code=real_code,
#             created=timezone.now()
#         )
#
#         # Check with wrong code
#         response = self.client.post(
#             self.signup_check_code_url,
#             {"email": email, "confirm_code": wrong_code},
#             format="json"
#         )
#
#         # Should fail with invalid code error
#         self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(response.data["detail"], "invalid_verification_code")
#
#     @patch('utils.email_service.EmailService.send_template_email')
#     def test_password_reset_send_code_success(self, mock_send_email):
#         """Test sending verification code for password reset - success case"""
#         mock_send_email.return_value = True
#
#         # Send verification code to existing user
#         response = self.client.post(
#             self.pw_reset_send_code_url,
#             {"email": "test@example.com"},  # Existing user
#             format="json"
#         )
#
#         # Check response
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertIn("expires_in_minutes", response.data)
#         self.assertIn("created_at", response.data)
#
#         # Check that code was created in DB
#         self.assertTrue(
#             ConfirmEmail.objects.filter(email="test@example.com").exists()
#         )
#
#         # Check that email was sent
#         mock_send_email.assert_called_once()
#
#     @patch('utils.email_service.EmailService.send_template_email')
#     def test_password_reset_send_code_nonexistent_email(self, mock_send_email):
#         """Test sending verification code for password reset - non-existent email"""
#         # Try to send code to non-existent email
#         response = self.client.post(
#             self.pw_reset_send_code_url,
#             {"email": "nonexistent@example.com"},
#             format="json"
#         )
#
#         # Should fail with NotEnrolledEmail
#         self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
#         self.assertEqual(response.data["detail"], "not_enrolled_login_id")
#
#         # Email should not be sent
#         mock_send_email.assert_not_called()
#
#     def test_password_reset_check_code_success(self):
#         """Test checking verification code for password reset - success case"""
#         email = "test@example.com"  # Existing user
#         code = "123456"
#
#         # Create the confirmation record
#         ConfirmEmail.objects.create(
#             email=email,
#             confirm_code=code,
#             created=timezone.now()
#         )
#
#         # Check the code
#         response = self.client.post(
#             self.pw_reset_check_code_url,
#             {"email": email, "confirm_code": code},
#             format="json"
#         )
#
#         # Should succeed and return token for force login
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertTrue(response.data["is_confirmed"])
#         self.assertIsNotNone(response.data["user"])
#         self.assertIsNotNone(response.data["token_info"])
#
#         # Record should be updated
#         conf_email = ConfirmEmail.objects.get(email=email)
#         self.assertTrue(conf_email.is_confirmed)
#
#     def test_non_prod_environment_code(self):
#         """Test that 000000 works as verification code in non-prod environments"""
#         email = "test_nonprod@example.com"
#
#         # Create confirmation code
#         ConfirmEmail.objects.create(
#             email=email,
#             confirm_code="000000",  # Default code for non-prod
#             created=timezone.now()
#         )
#
#         # Check the code
#         response = self.client.post(
#             self.signup_check_code_url,
#             {"email": email, "confirm_code": "000000"},
#             format="json"
#         )
#
#         # Should succeed
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertTrue(response.data["is_confirmed"])
