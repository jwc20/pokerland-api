from django.test import TestCase
from rest_framework.test import APIClient

CREDENTIALS = {"username": "alice", "password": "s3cret-Pass!"}


class CookieAuthFlowTests(TestCase):
    """The cookie-based JWT auth flow pokerland-client relies on."""

    def setUp(self):
        self.client = APIClient()

    def register(self):
        password = CREDENTIALS["password"]
        return self.client.post(
            "/api/auth/registration/",
            {"username": CREDENTIALS["username"], "password1": password, "password2": password},
            format="json",
        )

    def login(self):
        return self.client.post("/api/auth/login/", CREDENTIALS, format="json")

    def test_registration_signs_in_with_cookies_only(self):
        response = self.register()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["refresh"], "")
        self.assertIn("access_expiration", response.data)
        self.assertEqual(response.data["user"]["username"], "alice")
        self.assertTrue(response.cookies["access-token"]["httponly"])
        self.assertTrue(response.cookies["refresh-token"]["httponly"])
        self.assertEqual(self.client.get("/api/auth/user/").status_code, 200)

    def test_login_matches_registration_response(self):
        registered = self.register()
        self.client.post("/api/auth/logout/")

        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), set(registered.data))

    def test_refresh_uses_cookie(self):
        self.register()

        refreshed = self.client.post("/api/auth/token/refresh/", {}, format="json")
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(set(refreshed.data), {"access", "access_expiration"})
        self.assertEqual(self.client.get("/api/auth/user/").status_code, 200)

    def test_logout_clears_cookies_and_blacklists_refresh_token(self):
        refresh_token = self.register().cookies["refresh-token"].value

        logout = self.client.post("/api/auth/logout/")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(logout.cookies["access-token"]["max-age"], 0)
        self.assertEqual(logout.cookies["refresh-token"]["max-age"], 0)

        reused = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh_token}, format="json")
        self.assertEqual(reused.status_code, 401)

    def test_stale_access_cookie_does_not_block_login(self):
        self.register()
        self.client.cookies["access-token"] = "not-a-valid-token"

        self.assertEqual(self.client.get("/api/auth/user/").status_code, 401)
        self.assertEqual(self.login().status_code, 200)

    def test_invalid_authorization_header_is_rejected(self):
        self.register()

        response = APIClient().post(
            "/api/auth/login/", CREDENTIALS, format="json", HTTP_AUTHORIZATION="Bearer not-a-valid-token"
        )
        self.assertEqual(response.status_code, 401)
