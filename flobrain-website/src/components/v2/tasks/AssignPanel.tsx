"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { canAssignOther, type AssignActorRole } from "@/lib/v2/screens/assign";

export function AssignPanel({
  role,
  sameTeam,
  members,
  onAssign,
}: {
  role: AssignActorRole;
  sameTeam: boolean;
  members: Array<{ id: string; username: string | null }>;
  onAssign?: (userId: string) => void;
}) {
  const [userId, setUserId] = useState(members[0]?.id ?? "");
  const allowed = canAssignOther(role, sameTeam);
  if (!allowed) {
    return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">You can only assign yourself.</p>;
  }
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (userId) onAssign?.(userId);
      }}
    >
      <label className="text-sm">
        Assign to
        <select
          className="ms-2 rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-2 py-1"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
        >
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.username || member.id}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit">Assign</Button>
    </form>
  );
}
