from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from users.models import ClientToken

User = get_user_model()
URL = "/api/users/me/client-token/"


class ClientTokenTests(APITestCase):
    def test_new_users_get_a_unique_client_token(self):
        alice = User.objects.create_user("alice")
        bob = User.objects.create_user("bob")

        self.assertRegex(alice.client_token.key, r"^[0-9a-f]{32}$")
        self.assertNotEqual(alice.client_token.key, bob.client_token.key)

    def test_users_read_their_own_client_token(self):
        User.objects.create_user("alice")  # someone else's token comes first
        bob = User.objects.create_user("bob")
        self.client.force_authenticate(bob)

        response = self.client.get(URL)

        self.assertEqual(response.data, {"client_token": bob.client_token.key})

    def test_client_token_is_never_cached(self):
        self.client.force_authenticate(User.objects.create_user("alice"))

        response = self.client.get(URL)

        self.assertIn("no-store", response.get("Cache-Control", ""))

    def test_client_token_requires_sign_in(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_migration_gives_existing_users_a_client_token(self):
        alice = User.objects.create_user("alice")
        alice.client_token.delete()
        migration = import_module("users.migrations.0002_create_missing_client_tokens")

        migration.create_missing_client_tokens(apps, schema_editor=None)

        self.assertTrue(ClientToken.objects.filter(user=alice).exists())
