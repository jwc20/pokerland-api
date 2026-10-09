from django.urls import path

from leagues.views import (
    AssignmentDetailView,
    AssignmentListView,
    JoinView,
    LeagueDetailView,
    LeagueListView,
    MemberProgressView,
    MemberView,
    MyMembershipView,
    ProgressView,
)

urlpatterns = [
    path("", LeagueListView.as_view(), name="league-list"),
    path("join/", JoinView.as_view(), name="league-join"),
    path("<int:pk>/", LeagueDetailView.as_view(), name="league-detail"),
    path("<int:pk>/me/", MyMembershipView.as_view(), name="league-me"),
    path("<int:pk>/members/<int:member_pk>/", MemberView.as_view(), name="league-member"),
    path("<int:pk>/assignments/", AssignmentListView.as_view(), name="league-assignments"),
    path("<int:pk>/assignments/<int:assignment_pk>/", AssignmentDetailView.as_view(), name="league-assignment"),
    path("<int:pk>/progress/", ProgressView.as_view(), name="league-progress"),
    path("<int:pk>/progress/<int:member_pk>/", MemberProgressView.as_view(), name="league-member-progress"),
]
