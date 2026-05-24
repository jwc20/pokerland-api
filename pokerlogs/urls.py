from django.urls import path

from .views import AddGameAPIView, LogErrorsAPIView

urlpatterns = [
    path(
        "log/add-game",
        AddGameAPIView.as_view(),
        name="log-add-game",
    ),
    path(
        "log/log-errors",
        LogErrorsAPIView.as_view(),
        name="log-log-errors",
    ),
]
