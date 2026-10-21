"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import { filterRooms, roomsEmpty, unreadLabel, type RoomRow } from "@/lib/v2/screens/rooms";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function RoomsSidebar({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [rooms, setRooms] = useState<RoomRow[]>([]);
  const [query, setQuery] = useState("");
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .rooms(orgId)
      .then((rows) => {
        const next = rows as RoomRow[];
        setRooms(next);
        setState(roomsEmpty(next) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load rooms");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <aside className="w-64 border-e border-[color:var(--fb-v2-border)] p-4">
      <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Rooms</h2>
      <input
        className="mb-3 w-full rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-2 py-1 text-sm"
        placeholder="Search rooms"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ScreenBody state={state} error={error || orgError} emptyLabel="No rooms yet" onRetry={load}>
        <ul className="space-y-1">
          {filterRooms(rooms, query).map((room) => (
            <li key={room.id}>
              <Link href={`/w/${orgSlug}/rooms/${room.id}`} className="flex items-center justify-between gap-2">
                <span>{room.name}</span>
                {unreadLabel(room.unread) ? (
                  <span className="text-xs text-[color:var(--fb-v2-accent)]">{unreadLabel(room.unread)}</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      </ScreenBody>
    </aside>
  );
}
