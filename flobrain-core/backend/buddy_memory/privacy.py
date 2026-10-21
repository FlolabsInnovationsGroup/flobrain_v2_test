"""What the privacy center needs from buddy memory (export, inventory, erasure).

``privacy.services`` has no registry, so the lead wires these in (see docs/v2/features/MEMORY.md):
- ``build_export``: ``parts["buddy_memories.json"] = export_rows(user)``
- ``inventory``: ``"buddy_memories": count_for(user, org)``
- ``erase_member_data``: ``erase(org, user)`` (also done here by a signal when the request is done)
"""

from buddy_memory.models import MemoryItem
from buddy_memory.services import erase_person as erase  # noqa: F401
from buddy_memory.services import export_rows  # noqa: F401


def count_for(user, org) -> int:
    return MemoryItem.objects.filter(org=org, scope=MemoryItem.SCOPE_PERSON, user=user).count()
