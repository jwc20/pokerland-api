from django.urls import path

from hands.views import HandDaysView, HandDetailView, HandListView, HandTagsView

urlpatterns = [
    path("", HandListView.as_view(), name="hand-list"),
    path("days/", HandDaysView.as_view(), name="hand-days"),
    path("tags/", HandTagsView.as_view(), name="hand-tags"),
    path("<int:pk>/", HandDetailView.as_view(), name="hand-detail"),
]
