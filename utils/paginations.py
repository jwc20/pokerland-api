from collections import OrderedDict

from django.conf import settings
from django.core.paginator import InvalidPage
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class ApiPageNumberPagination(PageNumberPagination):
    """
    아래 2가지 이유로 drf 의 기본 PageNumberPagination override
    1. page_query_param 변경
    - 도메인에서 page라는 이름을 자주 사용할수 있을거 같아 api_page 로 키 변경
    2. 각 ListAPIView 에서 page_size 값 지정을 통해 page_size 변경

    swagger 문서에 반영하기 위해 CustomDjangoRestResponsePagination 적용
    """

    page_query_param = "api_page"
    page_size = settings.DEFAULT_PAGE_SIZE

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.
        """
        page_size = self.get_page_size(request, view)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = self.get_page_number(request, paginator)

        try:
            self.page = paginator.page(page_number)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(
                page_number=page_number, message=str(exc)
            )
            raise NotFound(msg)

        if paginator.num_pages > 1 and self.template is not None:
            # The browsable API should display pagination controls.
            self.display_page_controls = True

        self.request = request
        return list(self.page)

    def get_page_size(self, request, view):
        if hasattr(view, "page_size"):
            return view.page_size
        else:
            return super().get_page_size(request)

    def get_paginated_response_data(self, data):
        return OrderedDict(
            [
                ("count", self.page.paginator.count),
                ("current_page_number", self.page.number),
                ("total_page_count", self.page.paginator.num_pages),
                ("results", data),
            ]
        )

    def get_paginated_response(self, data):
        return Response(self.get_paginated_response_data(data))


def get_page_number(request):
    return int(request.query_params.get(ApiPageNumberPagination.page_query_param))
