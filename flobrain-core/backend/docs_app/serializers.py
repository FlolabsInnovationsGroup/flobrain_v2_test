from django.conf import settings
from rest_framework import serializers


def max_doc_chars() -> int:
    return int(getattr(settings, "FLOBRAIN_V2", {}).get("DOCUMENT_MAX_CHARS", 200_000))


class FilePresignSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    content_type = serializers.CharField(required=False, allow_blank=True, max_length=120)
    room = serializers.UUIDField(required=False)
    document = serializers.UUIDField(required=False)
    size = serializers.IntegerField(required=False, min_value=0)

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("name is required")
        if "/" in name or "\\" in name or name in {".", ".."} or "\x00" in name:
            raise serializers.ValidationError("name must not contain a path")
        return name

    def validate(self, attrs):
        if not attrs.get("room") and not attrs.get("document"):
            raise serializers.ValidationError("room or document is required")
        return attrs


class DocumentWriteSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    content_text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    version = serializers.IntegerField(required=False, min_value=0)

    def validate_content_text(self, value):
        if value and len(value) > max_doc_chars():
            raise serializers.ValidationError(f"A document can have at most {max_doc_chars()} characters")
        return value


class RestoreSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=0)
