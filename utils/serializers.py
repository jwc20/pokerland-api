from rest_framework import serializers


class ApiPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    current_page_number = serializers.IntegerField()
    total_page_count = serializers.IntegerField()


class ModelUpdateSerializer(serializers.ModelSerializer):
    """
    update 요청의 경우 모든 필드를 required=False, allow_blank=True 로 처리
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
            field.allow_blank = True
