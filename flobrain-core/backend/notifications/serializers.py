from rest_framework import serializers


class NotificationReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
