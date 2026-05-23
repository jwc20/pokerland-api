from collections import OrderedDict

from drf_yasg import openapi
from drf_yasg.inspectors import DjangoRestResponsePagination
from drf_yasg.openapi import Parameter, IN_QUERY
from rest_framework.pagination import (
    CursorPagination,
    LimitOffsetPagination,
    PageNumberPagination,
)


class CustomDjangoRestResponsePagination(DjangoRestResponsePagination):
    def get_paginated_response(self, paginator, response_schema):
        assert (
            response_schema.type == openapi.TYPE_ARRAY
        ), "array return expected for paged response"
        paged_schema = None
        if isinstance(
            paginator, (LimitOffsetPagination, PageNumberPagination, CursorPagination)
        ):
            has_count = not isinstance(paginator, CursorPagination)
            paged_schema = openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict(
                    (
                        (
                            "count",
                            (
                                openapi.Schema(type=openapi.TYPE_INTEGER)
                                if has_count
                                else None
                            ),
                        ),
                        (
                            "current_page_number",
                            openapi.Schema(type=openapi.TYPE_INTEGER),
                        ),
                        (
                            "total_page_count",
                            openapi.Schema(type=openapi.TYPE_INTEGER),
                        ),
                        ("results", response_schema),
                    )
                ),
                required=[
                    "results",
                    "current_page_number",
                    "total_page_count",
                    "count",
                ],
            )
        return paged_schema

    def get_paginator_parameters(self, paginator):
        return [
            Parameter(
                name=paginator.page_query_param,
                in_=IN_QUERY,
                required=True,
                type=openapi.TYPE_INTEGER,
            )
        ]
