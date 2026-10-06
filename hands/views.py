from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import CursorPagination

from hands.models import Hand
from hands.serializers import HandDetailSerializer, HandSummarySerializer


class HandPagination(CursorPagination):
    # A cursor, not page numbers: new hands arrive at the top while the user pages down.
    ordering = ("-played_at", "-id")
    page_size = 50


class HandListView(ListAPIView):
    """The signed-in user's hands, most recent first."""

    serializer_class = HandSummarySerializer
    pagination_class = HandPagination

    def get_queryset(self):
        return Hand.objects.filter(user=self.request.user).defer("replay")


class HandDetailView(RetrieveAPIView):
    """One of the signed-in user's hands, with what its replay needs."""

    serializer_class = HandDetailSerializer

    def get_queryset(self):
        return Hand.objects.filter(user=self.request.user)
