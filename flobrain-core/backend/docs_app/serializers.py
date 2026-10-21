from rest_framework import serializers


class FilePresignSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    content_type = serializers.CharField(required=False, allow_blank=True, max_length=120)
    room = serializers.UUIDField()

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("name is required")
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise serializers.ValidationError("name must not contain a path")
        return name


class DocumentWriteSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    content_text = serializers.CharField(required=False, allow_blank=True)
    version = serializers.IntegerField(required=False, min_value=0)
