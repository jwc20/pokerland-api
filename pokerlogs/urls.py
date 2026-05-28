from django.urls import path

from .views import AddGameAPIView, GameHistoryAPIView, LogErrorsAPIView, MyGameHistoryAPIView

urlpatterns = [
    path(
        "log/add-game",
        AddGameAPIView.as_view(),
        name="log-add-game",
    ),
    path(
        "log/my-game-history",
        MyGameHistoryAPIView.as_view(),
        name="log-my-game-history",
    ),
    path(
        "log/game-history",
        GameHistoryAPIView.as_view(),
        name="log-game-history",
    ),
    path(
        "log/log-errors",
        LogErrorsAPIView.as_view(),
        name="log-log-errors",
    ),
]
