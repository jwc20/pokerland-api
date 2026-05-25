from rest_framework import serializers


class ApiPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    current_page_number = serializers.IntegerField()
    total_page_count = serializers.IntegerField()


class ModelUpdateSerializer(serializers.ModelSerializer):
    """
    For update requests, treat all fields as required=False.
    CharField subclasses also get allow_blank=True so empty strings are accepted.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
            if isinstance(field, serializers.CharField):
                field.allow_blank = True
