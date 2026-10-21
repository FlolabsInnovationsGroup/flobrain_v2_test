from rest_framework import serializers


class MeetingCreateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_title(self, value):
        return (value or "").strip() or "Meeting"


class ActionItemConfirmSerializer(serializers.Serializer):
    confirm = serializers.BooleanField(required=False)
    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    due_on = serializers.DateField(required=False, allow_null=True)
