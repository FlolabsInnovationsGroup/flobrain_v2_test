from django.conf import settings
from rest_framework import serializers


class RoomCreateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    user_id = serializers.UUIDField(required=False)
    team = serializers.UUIDField(required=False)
    user_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)


class RoomPatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)


class RoomMessageSerializer(serializers.Serializer):
    body = serializers.CharField()

    def validate_body(self, value):
        text = (value or "").strip()
        if not text:
            raise serializers.ValidationError("body is required")
        max_len = getattr(settings, "FLOBRAIN_V2", {}).get("ROOM_MESSAGE_MAX_LENGTH", 8000)
        if len(text) > max_len:
            raise serializers.ValidationError(f"body must be at most {max_len} characters")
        return text


class AnnouncementCreateSerializer(serializers.Serializer):
    room = serializers.UUIDField()
    body = serializers.CharField()

    def validate_body(self, value):
        text = (value or "").strip()
        if not text:
            raise serializers.ValidationError("body is required")
        if len(text) > 8000:
            raise serializers.ValidationError("body must be at most 8000 characters")
        return text


class TranslateQuerySerializer(serializers.Serializer):
    translate_to = serializers.CharField(required=False, allow_blank=True, max_length=8)

    def validate_translate_to(self, value):
        language = (value or "").strip()
        if not language:
            return ""
        import re

        if not re.fullmatch(r"[a-z]{2}(?:-[A-Za-z]{2})?", language):
            raise serializers.ValidationError("translate_to must be a language code")
        return language.lower()
