import gzip
import json

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from auth_tokens.utils import CreateToken
from users.models import hash_client_token
from users.factories import CustomerFactory, StaffFactory

from .models import ErrorLog, GameLog


class ClientLogSubmissionTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = CustomerFactory()
        self.client_token = "client-token"
        self.client_token_hash = hash_client_token(self.client_token)
        self.user.client_token_hash = self.client_token_hash.upper()
        self.user.save(update_fields=["client_token_hash"])

    def _payload(self, **overrides):
        payload = {
            "client_token_hash": self.client_token_hash,
            "client": "pokerstars",
            "client_version": "0.1.0",
            "submitted_at": "2026-06-03T12:00:00Z",
            "hand_id": "hand-1",
        }
        payload.update(overrides)
        return payload

    def test_add_game_accepts_valid_client_token_hash_and_associates_user(self):
        response = self.client.post(
            reverse("log-add-game"), self._payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        game_log = GameLog.objects.get()
        self.assertEqual(game_log.user, self.user)
        self.assertEqual(game_log.client, "pokerstars")
        self.assertEqual(game_log.client_version, "0.1.0")
        self.assertEqual(game_log.payload, {"hand_id": "hand-1"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.client_token_hash, self.client_token_hash)

    def test_log_errors_accepts_valid_client_token_hash_and_associates_user(self):
        response = self.client.post(
            reverse("log-log-errors"),
            self._payload(source="hud", error={"message": "boom"}),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        error_log = ErrorLog.objects.get()
        self.assertEqual(error_log.user, self.user)
        self.assertEqual(error_log.client, "pokerstars")
        self.assertEqual(
            error_log.payload,
            {"hand_id": "hand-1", "source": "hud", "error": {"message": "boom"}},
        )

    def test_missing_client_token_hash_returns_validation_error(self):
        payload = self._payload()
        payload.pop("client_token_hash")

        response = self.client.post(reverse("log-add-game"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("client_token_hash", response.json())

    def test_malformed_client_token_hash_returns_validation_error(self):
        response = self.client.post(
            reverse("log-add-game"),
            self._payload(client_token_hash="not-hex"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("client_token_hash", response.json())

    def test_unknown_well_formed_client_token_hash_returns_unauthorized(self):
        response = self.client.post(
            reverse("log-add-game"),
            self._payload(client_token_hash="a" * 64),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json(), {"detail": "Invalid client_token_hash."})

    def test_uuid_v4_token_is_rejected(self):
        response = self.client.post(
            reverse("log-add-game"),
            self._payload(client_token_hash="123e4567-e89b-12d3-a456-426614174000"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_jwt_like_token_is_rejected(self):
        response = self.client.post(
            reverse("log-add-game"),
            self._payload(client_token_hash="aaa.bbb.ccc"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_drf_token_length_value_is_rejected(self):
        response = self.client.post(
            reverse("log-add-game"),
            self._payload(client_token_hash="a" * 40),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_style_salted_hash_is_rejected(self):
        response = self.client.post(
            reverse("log-add-game"),
            self._payload(
                client_token_hash="pbkdf2_sha256$720000$salt$hash"
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_gzipped_json_request_is_accepted(self):
        body = gzip.compress(json.dumps(self._payload()).encode())

        response = self.client.post(
            reverse("log-add-game"),
            body,
            content_type="application/json",
            HTTP_CONTENT_ENCODING="gzip",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(GameLog.objects.get().user, self.user)

    def test_plain_json_request_is_accepted(self):
        response = self.client.post(
            reverse("log-add-game"), self._payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class GameHistoryAPIViewTest(TestCase):
    def test_my_game_history_returns_authenticated_users_paginated_game_logs(self):
        user = CustomerFactory()
        other_user = CustomerFactory()
        token_value, _ = CreateToken(user=user).create()
        own_log = GameLog.objects.create(
            user=user,
            token="own-token",
            client="desktop",
            client_version="1.0.0",
            payload={"hand_id": "own-hand"},
        )
        GameLog.objects.create(
            user=other_user,
            token="other-token",
            client="desktop",
            client_version="1.0.0",
            payload={"hand_id": "other-hand"},
        )

        response = APIClient().get(
            reverse("log-my-game-history"),
            {"api_page": 1},
            HTTP_TOKEN=token_value,
            HTTP_app_version="1.0.1",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["count"], 1)
        self.assertEqual(response_data["current_page_number"], 1)
        self.assertEqual(response_data["total_page_count"], 1)
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["id"], str(own_log.id))

    def test_my_game_history_requires_token_authentication(self):
        response = APIClient().get(
            reverse("log-my-game-history"),
            {"api_page": 1},
            HTTP_app_version="1.0.1",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_all_game_history_returns_paginated_logs_for_staff(self):
        staff = StaffFactory()
        first_user = CustomerFactory()
        second_user = CustomerFactory()
        token_value, _ = CreateToken(user=staff).create()
        first_log = GameLog.objects.create(
            user=first_user,
            token="first-token",
            client="desktop",
            client_version="1.0.0",
            payload={"hand_id": "first-hand"},
        )
        second_log = GameLog.objects.create(
            user=second_user,
            token="second-token",
            client="desktop",
            client_version="1.0.0",
            payload={"hand_id": "second-hand"},
        )

        response = APIClient().get(
            reverse("log-game-history"),
            {"api_page": 1},
            HTTP_TOKEN=token_value,
            HTTP_app_version="1.0.1",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["count"], 2)
        self.assertEqual(response_data["current_page_number"], 1)
        self.assertEqual(response_data["total_page_count"], 1)
        self.assertEqual(
            {result["id"] for result in response_data["results"]},
            {str(first_log.id), str(second_log.id)},
        )
        self.assertEqual(
            {result["user"] for result in response_data["results"]},
            {first_user.id, second_user.id},
        )

    def test_all_game_history_rejects_non_staff_users(self):
        user = CustomerFactory()
        token_value, _ = CreateToken(user=user).create()

        response = APIClient().get(
            reverse("log-game-history"),
            {"api_page": 1},
            HTTP_TOKEN=token_value,
            HTTP_app_version="1.0.1",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
