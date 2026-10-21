"use client";

import Link from "next/link";
import { useState } from "react";

import { roomTitle, type RoomInfo } from "@/components/v2/rooms/format";
import { NewDirectMessage, NewGroupRoom } from "@/components/v2/rooms/NewRoomForms";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

type Mode = "" | "dm" | "group";

/** Every room you're in, reachable even when Focus mode hides the rooms panel. */
export function RoomsIndexScreen({ orgSlug, initialMode = "" }: { orgSlug: string; initialMode?: Mode }) {
  const tr = useTr();
  const { access, orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<RoomInfo[]>(orgId, "/rooms", { list: true });
  const [mode, setMode] = useState<Mode>(initialMode);
  const [query, setQuery] = useState("");
  const canChat = has(access, "chat.use");
  const canManage = has(access, "room.manage");

  const q = query.trim().toLowerCase();
  const rooms = (data ?? []).filter((room) => !q || roomTitle(room).toLowerCase().includes(q));
  const groups: { title: string; rows: RoomInfo[] }[] = [
    { title: tr("Team and project rooms"), rows: rooms.filter((r) => r.kind === "team" || r.kind === "project") },
    { title: tr("Direct messages"), rows: rooms.filter((r) => r.kind === "direct") },
    { title: tr("Group rooms"), rows: rooms.filter((r) => r.kind === "group") },
  ];

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={tr("Rooms")}
        intro={tr("Your team and project rooms, direct messages and group rooms.")}
        action={
          <div className="flex flex-wrap gap-2">
            {canChat ? (
              <Button type="button" variant="outline" onClick={() => setMode("dm")}>
                {tr("New direct message")}
              </Button>
            ) : null}
            {canManage ? (
              <Button type="button" onClick={() => setMode("group")}>
                {tr("New room")}
              </Button>
            ) : null}
          </div>
        }
      />
      {orgId && mode === "dm" && canChat ? (
        <div className="mb-6">
          <NewDirectMessage orgId={orgId} orgSlug={orgSlug} selfId={access?.user_id} onCancel={() => setMode("")} />
        </div>
      ) : null}
      {orgId && mode === "group" && canManage ? (
        <div className="mb-6">
          <NewGroupRoom orgId={orgId} orgSlug={orgSlug} selfId={access?.user_id} onCancel={() => setMode("")} />
        </div>
      ) : null}
      <input
        className="v2-input mb-4"
        aria-label={tr("Search rooms")}
        placeholder={tr("Search rooms")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ScreenBody state={state} error={error} emptyLabel={tr("No rooms yet")} onRetry={reload}>
        {groups.map((group) =>
          group.rows.length ? (
            <Section key={group.title} title={group.title}>
              <Rows>
                {group.rows.map((room) => (
                  <Row key={room.id}>
                    <Link href={`/w/${orgSlug}/rooms/${room.id}`} className="font-medium hover:underline">
                      {roomTitle(room)}
                    </Link>
                    {room.unread ? <Badge tone="accent">{tr("{n} unread", { n: room.unread > 99 ? "99+" : room.unread })}</Badge> : null}
                  </Row>
                ))}
              </Rows>
            </Section>
          ) : null,
        )}
      </ScreenBody>
    </div>
  );
}
