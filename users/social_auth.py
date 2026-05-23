from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import firebase_admin  # remove later
import jwt
import requests
from django.conf import settings
from django.utils import timezone
from firebase_admin import auth
from google.auth.transport import requests
from google.oauth2 import id_token

from utils.exceptions import TokenAuthenticationFailed

# import requests


class SocialAuthModule(ABC):
    @abstractmethod
    def check(self, access_token) -> tuple[str, str]:
        pass

    @abstractmethod
    def withdrawal(self, user_identifier):
        pass


class GoogleAuthModule(SocialAuthModule):
    def check(self, access_token):
        user_info = self._get_google_user_info(access_token)
        if user_info is None or not user_info.get("valid"):
            return None, None
        return user_info.get("uid"), user_info.get("email")

    def withdrawal(self, user_identifier):
        """Google login has no withdrawal logic."""
        pass

    def _get_google_user_info(self, access_token):
        try:
            response = self._handle_id_token(access_token)

            if not response.get("valid"):
                print(
                    f"Invalid or expired token: {response.get('message') or response.get('error')}"
                )
                return None

            uid = response.get("uid")
            # email = response.get("email")

            try:
                user = auth.get_user(uid)
            except auth.UserNotFoundError:
                user = auth.create_user(uid=uid)
                print(f"Created new Firebase user: {user.uid}")

            return response

        except Exception as e:
            print(f"Error verifying Google token: {e}")
            return None

    def _handle_id_token(self, id_token_str: str):
        import time

        try:
            decoded = jwt.decode(id_token_str, options={"verify_signature": False})
            exp = decoded.get("exp", 0)
            now = int(time.time())

            if now > exp:
                return {
                    "valid": False,
                    "message": "Token has expired. Please refresh it on the client.",
                }

            id_info = id_token.verify_oauth2_token(id_token_str, requests.Request())

            return {"valid": True, "uid": id_info["sub"], "email": id_info.get("email")}

        except Exception as e:
            return {"valid": False, "error": str(e)}


class AppleAuthModule(SocialAuthModule):
    def check(self, access_token):

        ################################# TODO
        user_info = self._get_apple_user_info(access_token)
        if user_info is None:
            return None, None
        return user_info.get("sub"), user_info.get("email")

    def withdrawal(self, user_identifier):
        pass

    def _get_apple_user_info(self, identity_token):
        try:
            decoded = jwt.decode(
                identity_token,
                "",  # Use an empty string because verification uses Apple's public key.
                options={
                    "verify_signature": False,  # Skip signature verification.
                    "verify_aud": False,  # TODO
                },
                # audience=settings.IOS_BUNDLE_ID,  # Use bundle_id from environment variable.
            )
            return decoded
        except Exception as e:
            return None

    def revoke_apple_token(self, user_identifier: str):
        """Revoke Apple account linkage."""
        try:
            # Generate client secret
            client_secret = self._create_client_secret()

            # Apple token revocation endpoint
            url = "https://appleid.apple.com/auth/revoke"

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            data = {
                "client_id": settings.APPLE_BUNDLE_ID,
                "client_secret": client_secret,
                "token": user_identifier,  # User identifier (sub claim)
                "token_type_hint": "access_token",
            }

            response = requests.post(url, headers=headers, data=data)

            if response.status_code == 200:
                # Token revoked successfully
                return True
            return False

        except Exception as e:
            print(f"Error revoking Apple token: {e}")
            return False

    def _create_client_secret(self):
        """Create Apple client secret."""
        now = timezone.now()
        exp_time = now + timedelta(days=180)  # Valid for 180 days.

        headers = {"kid": settings.APPLE_SUBSCRIPTION_KEY_ID, "alg": "ES256"}

        payload = {
            "iss": settings.IOS_TEAM_ID,
            "iat": int(now.timestamp()),
            "exp": int(exp_time.timestamp()),
            "aud": "https://appleid.apple.com",
            "sub": settings.IOS_BUNDLE_ID,
        }

        # Create JWT token
        client_secret = jwt.encode(
            payload, settings.APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers
        )

        return client_secret
