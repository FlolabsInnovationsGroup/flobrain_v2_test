"use client";

import { Avatar, Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

export type RoomMemberRow = { user_id: string; name: string; presence: string; active: boolean };

const DOT: Record<string, string> = {
  online: "var(--fb-v2-success)",
  away: "var(--fb-v2-waiting)",
  on_leave: "var(--fb-v2-text-muted)",
  offline: "var(--fb-v2-border)",
};

export function presenceLabel(presence: string, tr: (s: string) => string): string {
  if (presence === "online") return tr("presence|Online");
  if (presence === "away") return tr("presence|Away");
  if (presence === "on_leave") return tr("presence|On leave");
  return tr("presence|Offline");
}

/** Who is in the room and whether they're around right now. */
export function RoomMembersPanel({ members, selfId }: { members: RoomMemberRow[]; selfId?: string }) {
  const tr = useTr();
  const online = members.filter((m) => m.active && m.presence === "online").length;
  return (
    <aside aria-label={tr("Members")} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <h2 className="mb-1 font-semibold">{tr("Members")}</h2>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("{n} of {total} online", { n: online, total: members.length })}</p>
      <ul className="space-y-2">
        {members.map((member) => (
          <li key={member.user_id} className={member.active ? "flex items-center gap-2" : "flex items-center gap-2 opacity-60"}>
            <span className="relative">
              <Avatar name={member.name} size={28} />
              <span
                aria-hidden
                className="absolute -bottom-0.5 -end-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-[color:var(--fb-v2-surface)]"
                style={{ background: DOT[member.presence] ?? DOT.offline }}
              />
            </span>
            <span className="min-w-0 flex-1 truncate text-sm">
              {member.name}
              {member.user_id === selfId ? <span className="text-[color:var(--fb-v2-text-muted)]"> {tr("(you)")}</span> : null}
            </span>
            {member.active ? (
              <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{presenceLabel(member.presence, tr)}</span>
            ) : (
              <Badge>{tr("Inactive")}</Badge>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}
