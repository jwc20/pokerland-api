import logging
from abc import ABC, abstractmethod
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from utils.exceptions import TokenAuthenticationFailed

logger = logging.getLogger(__name__)


class SocialAuthModule(ABC):
    @abstractmethod
    def check(self, access_token: str) -> tuple[str | None, str | None]:
        pass

    @abstractmethod
    def withdrawal(self, user_identifier: str) -> None:
        pass


class GoogleAuthModule(SocialAuthModule):
    def check(self, access_token: str) -> tuple[str | None, str | None]:
        user_info = self._get_google_user_info(access_token)
        if user_info is None or not user_info.get("valid"):
            return None, None
        return user_info.get("uid"), user_info.get("email")

    def withdrawal(self, user_identifier: str) -> None:
        """Google login has no withdrawal logic."""
        pass

    def _get_google_user_info(self, access_token: str) -> dict | None:
        try:
            id_info = id_token.verify_oauth2_token(
                access_token, google_requests.Request()
            )
            return {
                "valid": True,
                "uid": id_info["sub"],
                "email": id_info.get("email"),
            }
        except ValueError as e:
            logger.warning("Invalid or expired Google token: %s", e)
            return None
        except Exception as e:
            logger.error("Error verifying Google token: %s", e)
            return None


class AppleAuthModule(SocialAuthModule):
    def check(self, access_token: str) -> tuple[str | None, str | None]:
        # TODO: Implement proper Apple JWT signature verification
        # against Apple's public keys (https://appleid.apple.com/auth/keys).
        user_info = self._get_apple_user_info(access_token)
        if user_info is None:
            return None, None
        return user_info.get("sub"), user_info.get("email")

    def withdrawal(self, user_identifier: str) -> None:
        pass

    def _get_apple_user_info(self, identity_token: str) -> dict | None:
        try:
            # WARNING: Signature verification is skipped here.
            # This should be replaced with proper verification using Apple's
            # public keys before going to production.
            decoded = jwt.decode(
                identity_token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                },
            )
            return decoded
        except jwt.ExpiredSignatureError:
            logger.warning("Apple identity token has expired")
            return None
        except jwt.DecodeError as e:
            logger.warning("Failed to decode Apple identity token: %s", e)
            return None

    def revoke_apple_token(self, user_identifier: str) -> bool:
        """Revoke Apple account linkage."""
        try:
            import requests

            client_secret = self._create_client_secret()

            url = "https://appleid.apple.com/auth/revoke"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {
                "client_id": settings.APPLE_BUNDLE_ID,
                "client_secret": client_secret,
                "token": user_identifier,
                "token_type_hint": "access_token",
            }

            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                return True
            return False

        except Exception as e:
            logger.error("Error revoking Apple token: %s", e)
            return False

    def _create_client_secret(self) -> str:
        """Create Apple client secret."""
        now = timezone.now()
        exp_time = now + timedelta(days=180)

        headers = {"kid": settings.APPLE_SUBSCRIPTION_KEY_ID, "alg": "ES256"}

        payload = {
            "iss": settings.IOS_TEAM_ID,
            "iat": int(now.timestamp()),
            "exp": int(exp_time.timestamp()),
            "aud": "https://appleid.apple.com",
            "sub": settings.IOS_BUNDLE_ID,
        }

        client_secret = jwt.encode(
            payload, settings.APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers
        )

        return client_secret
