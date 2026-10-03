from functools import cache
from io import StringIO

from django.core.management import call_command
from drf_spectacular.drainage import reset_generator_stats
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient, APITestCase

PASSWORD = "s3cret-Pass!"


def register(client, username="alice"):
    data = {"username": username, "password1": PASSWORD, "password2": PASSWORD}
    return client.post("/api/auth/registration/", data, format="json")


def login(client, username="alice"):
    return client.post("/api/auth/login/", {"username": username, "password": PASSWORD}, format="json")


def refresh(client, data=None):
    return client.post("/api/auth/token/refresh/", data or {}, format="json")


@cache
def openapi_schema():
    return SchemaGenerator().get_schema(request=None, public=True)


class AuthTests(APITestCase):
    """The cookie-based JWT auth pokerland-client relies on."""

    def test_registering_signs_the_user_in(self):
        register(self.client)

        self.assertEqual(self.client.get("/api/auth/user/").status_code, 200)

    def test_refresh_token_is_only_sent_as_an_http_only_cookie(self):
        response = register(self.client)

        self.assertEqual(response.data["refresh"], "")
        self.assertTrue(response.cookies["refresh-token"]["httponly"])

    def test_login_responds_like_registration(self):
        registered = register(self.client)

        response = login(APIClient())

        self.assertEqual(set(response.data), set(registered.data))

    def test_refreshing_renews_the_access_cookie(self):
        register(self.client)

        response = refresh(self.client)

        self.assertEqual(response.status_code, 200)
        self.assertIn("access-token", response.cookies)

    def test_logging_out_ends_the_session(self):
        refresh_token = register(self.client).cookies["refresh-token"].value

        response = self.client.post("/api/auth/logout/")

        self.assertEqual(response.cookies["access-token"]["max-age"], 0)
        self.assertEqual(refresh(APIClient(), {"refresh": refresh_token}).status_code, 401)

    def test_a_stale_access_cookie_does_not_block_login(self):
        register(self.client)
        self.client.cookies["access-token"] = "stale"

        self.assertEqual(login(self.client).status_code, 200)

    def test_an_invalid_bearer_token_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid")

        self.assertEqual(login(self.client).status_code, 401)


class SchemaTests(APITestCase):
    """The OpenAPI schema pokerland-client generates its API client from."""

    def assertResponseMatchesSchema(self, response):
        schema = openapi_schema()
        operation = schema["paths"][response.request["PATH_INFO"]][response.request["REQUEST_METHOD"].lower()]
        content = operation["responses"][str(response.status_code)]["content"]
        component = content["application/json"]["schema"]["$ref"].rpartition("/")[2]
        self.assertEqual(set(schema["components"]["schemas"][component]["properties"]), set(response.data))

    def test_schema_generates_cleanly(self):
        reset_generator_stats()  # warnings are counted per process
        call_command("spectacular", validate=True, fail_on_warn=True, stdout=StringIO())

    def test_auth_responses_match_the_schema(self):
        self.assertResponseMatchesSchema(register(self.client))
        self.assertResponseMatchesSchema(login(APIClient()))
        self.assertResponseMatchesSchema(refresh(self.client))

    def test_refreshing_needs_no_request_body(self):
        refresh_request = openapi_schema()["components"]["schemas"]["TokenRefreshRequest"]

        self.assertNotIn("required", refresh_request)
