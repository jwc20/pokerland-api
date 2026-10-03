from django.urls import path

from users.views import ClientTokenView

urlpatterns = [
    path("me/client-token/", ClientTokenView.as_view(), name="client-token"),
]
