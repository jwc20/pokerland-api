from django.urls import path

from explain.views import (
    BriefView,
    CatalogView,
    ExplanationDetailView,
    ExplanationListView,
    SpendView,
    TurnBriefView,
    TurnListView,
)

urlpatterns = [
    path("", ExplanationListView.as_view(), name="explanation-list"),
    path("models/", CatalogView.as_view(), name="explanation-models"),
    path("spend/", SpendView.as_view(), name="explanation-spend"),
    path("brief/", BriefView.as_view(), name="explanation-brief"),
    path("<int:pk>/", ExplanationDetailView.as_view(), name="explanation-detail"),
    path("<int:pk>/turns/brief/", TurnBriefView.as_view(), name="explanation-turn-brief"),
    path("<int:pk>/turns/", TurnListView.as_view(), name="explanation-turns"),
]
