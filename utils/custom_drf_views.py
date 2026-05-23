from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response

from utils.paginations import ApiPageNumberPagination


class CustomListAPIViewException(Exception):
    pass


class CustomRetrieveListAPIViewSetMixin(
    ListModelMixin, RetrieveModelMixin, GenericAPIView
):
    """
    아래와 같은 이유로 drf 의 기본 ListAPIView를 상속받아 오버라이딩 함
    1. 매번 list API 에서 pagination을 선언하지 않아도 됨.
    2. drf-yasg 에서 제공해주는 Serializer를 사용한 query_params 문서 자동화 활용
    3. query_params_serializer의 선택지에 all을 추가하는 경우, 해당 조건을 무시하도록 설정

    아래 기능들을 기본으로 포함한다.
    1. 새로 오버라이딩 한 ApiPageNumberPagination 를 통해 pagination 처리
    2. query_params 을 통한 filter 기능
    - query_serializer 에 query_params 을 검증할 Serializer를 지정한다.
    """

    disable_filter = False
    query_params_serializer = None
    pagination_class = ApiPageNumberPagination

    def retrieve(self, request, *args, **kwargs):
        if not self.disable_filter and not self.query_params_serializer:
            raise CustomListAPIViewException("need query_serializer")
        return super().retrieve(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        # 아래 부분 커스터마이징
        queryset = self.get_queryset()
        query_params_serializer = self.query_params_serializer(
            data=request.query_params
        )
        query_params_serializer.is_valid(raise_exception=True)
        validated_data = query_params_serializer.validated_data

        all_values = []
        for k, v in validated_data.items():
            if v == "all":
                all_values.append(k)

        for key in all_values:
            validated_data.pop(key, None)

        queryset = queryset.filter(**validated_data)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
