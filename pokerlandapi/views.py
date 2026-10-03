from dj_rest_auth.registration.views import RegisterView as BaseRegisterView
from dj_rest_auth.views import LoginView
from drf_spectacular.utils import extend_schema
from rest_framework import status


@extend_schema(responses={status.HTTP_201_CREATED: LoginView().get_response_serializer()})
class RegisterView(BaseRegisterView):
    """Registers a new user and signs them in the same way LoginView does.

    dj-rest-auth's RegisterView sets no auth cookies and returns the refresh
    token in the body, so the client would not be signed in and the refresh
    token would reach JavaScript despite JWT_AUTH_HTTPONLY.
    """

    access_token = None

    def perform_create(self, serializer):
        self.user = super().perform_create(serializer)
        return self.user

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if self.access_token is None:
            return response  # e.g. mandatory email verification: no one is signed in yet

        login = LoginView(request=request, format_kwarg=self.format_kwarg)
        login.user = self.user
        login.access_token = self.access_token
        login.refresh_token = self.refresh_token
        response = login.get_response()
        response.status_code = status.HTTP_201_CREATED
        return response
