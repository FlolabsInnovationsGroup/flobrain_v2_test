from rest_framework import serializers

from .models import MemoryNode

MEMORY_TYPE_CHOICES = [choice[0] for choice in MemoryNode._meta.get_field("memory_type").choices]


class MemoryNodePatchSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=False)
    memory_type = serializers.ChoiceField(choices=MEMORY_TYPE_CHOICES, required=False)
    relevance = serializers.FloatField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No editable fields provided")
        return attrs
