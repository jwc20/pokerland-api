from django.urls import path

from hands.views import HandDetailView, HandListView

urlpatterns = [
    path("", HandListView.as_view(), name="hand-list"),
    path("<int:pk>/", HandDetailView.as_view(), name="hand-detail"),
]
