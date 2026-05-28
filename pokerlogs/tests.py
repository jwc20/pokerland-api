from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from auth_tokens.utils import CreateToken
from users.factories import CustomerFactory, StaffFactory

from .models import GameLog


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
