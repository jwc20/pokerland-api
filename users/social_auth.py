from abc import ABC, abstractmethod
import requests
from utils.exceptions import TokenAuthenticationFailed
import jwt
from django.conf import settings
from datetime import datetime, timedelta
from django.utils import timezone


from google.oauth2 import id_token
from google.auth.transport import requests

import firebase_admin
from firebase_admin import auth
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
        """구글 로그인은 탈퇴 로직 없음"""
        pass

    def _get_google_user_info(self, access_token):
        try:
            response = self._handle_id_token(access_token)

            if not response.get("valid"):
                print(f"Invalid or expired token: {response.get('message') or response.get('error')}")
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
                    "message": "Token has expired. Please refresh it on the client."
                }

            id_info = id_token.verify_oauth2_token(id_token_str, requests.Request())

            return {
                "valid": True,
                "uid": id_info["sub"],
                "email": id_info.get("email")
            }

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
                "",  # 애플 공개키로 검증하므로 빈 문자열 사용
                options={
                    "verify_signature": False,  # 서명 확인 건너뛰기
                    "verify_aud": False,  # TODO
                },
                # audience=settings.IOS_BUNDLE_ID,  # 환경변수에서 가져온 bundle_id 사용
            )
            return decoded
        except Exception as e:
            return None

    def revoke_apple_token(self, user_identifier: str):
        """애플 계정 연동 해제"""
        try:
            # 클라이언트 시크릿 생성
            client_secret = self._create_client_secret()

            # Apple 토큰 철회 엔드포인트
            url = "https://appleid.apple.com/auth/revoke"

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            data = {
                "client_id": settings.APPLE_BUNDLE_ID,
                "client_secret": client_secret,
                "token": user_identifier,  # 사용자의 identifier (sub 값)
                "token_type_hint": "access_token",
            }

            response = requests.post(url, headers=headers, data=data)

            if response.status_code == 200:
                # 성공적으로 철회된 경우 사용자 삭제
                return True
            return False

        except Exception as e:
            print(f"Error revoking Apple token: {e}")
            return False

    def _create_client_secret(self):
        """Apple Client Secret 생성"""
        now = timezone.now()
        exp_time = now + timedelta(days=180)  # 180일 유효기간

        headers = {"kid": settings.APPLE_SUBSCRIPTION_KEY_ID, "alg": "ES256"}

        payload = {
            "iss": settings.IOS_TEAM_ID,
            "iat": int(now.timestamp()),
            "exp": int(exp_time.timestamp()),
            "aud": "https://appleid.apple.com",
            "sub": settings.IOS_BUNDLE_ID,
        }

        # JWT 토큰 생성
        client_secret = jwt.encode(
            payload, settings.APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers
        )

        return client_secret
