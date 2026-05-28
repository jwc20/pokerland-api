from django.urls import path

from .views import (
    AddGameAPIView,
    AllGameLogsAPIView,
    LogErrorsAPIView,
    MyGameLogsAPIView,
    UserGameLogsAPIView,
)

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
    path(
        "log/my-game-logs",
        MyGameLogsAPIView.as_view(),
        name="log-my-game-logs",
    ),
    path(
        "log/user/<str:username>/game-logs",
        UserGameLogsAPIView.as_view(),
        name="log-user-game-logs",
    ),
    path(
        "log/all-game-logs",
        AllGameLogsAPIView.as_view(),
        name="log-all-game-logs",
    ),
]
