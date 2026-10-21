from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from rest_framework import serializers


class ToolWriteSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=80)
    url = serializers.CharField(required=False, allow_blank=True)
    sort_order = serializers.IntegerField(required=False, min_value=0)

    def validate_url(self, value):
        url = (value or "").strip()
        if not url:
            raise serializers.ValidationError("url is invalid")
        try:
            URLValidator(schemes=["http", "https"])(url)
        except DjangoValidationError as exc:
            raise serializers.ValidationError("url is invalid") from exc
        return url
