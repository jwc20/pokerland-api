from django.urls import path

from tracker.views import ChunkView, ConfigView, MeView, StreamView, TrackerStatusView

urlpatterns = [
    # Called by the trackers, with the client token.
    path("me/", MeView.as_view(), name="tracker-me"),
    path("config/", ConfigView.as_view(), name="tracker-config"),
    path("streams/<uuid:stream_id>/", StreamView.as_view(), name="tracker-stream"),
    path("streams/<uuid:stream_id>/chunks/<int:start>/", ChunkView.as_view(), name="tracker-chunk"),
    # Called by the web app, with the JWT cookies.
    path("status/", TrackerStatusView.as_view(), name="tracker-status"),
]
