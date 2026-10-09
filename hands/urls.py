from django.urls import path

from hands.views import (
    HandBoardView,
    HandDaysView,
    HandDetailView,
    HandListView,
    HandNoteDetailView,
    HandNotesView,
    HandOutsView,
    HandTagsView,
)

urlpatterns = [
    path("", HandListView.as_view(), name="hand-list"),
    path("days/", HandDaysView.as_view(), name="hand-days"),
    path("tags/", HandTagsView.as_view(), name="hand-tags"),
    path("<int:pk>/", HandDetailView.as_view(), name="hand-detail"),
    path("<int:pk>/notes/", HandNotesView.as_view(), name="hand-notes"),
    path("<int:pk>/notes/<int:note_id>/", HandNoteDetailView.as_view(), name="hand-note"),
    path("<int:pk>/outs/", HandOutsView.as_view(), name="hand-outs"),
    path("<int:pk>/board/", HandBoardView.as_view(), name="hand-board"),
]
