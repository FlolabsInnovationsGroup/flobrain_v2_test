"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { roomTitle, type RoomInfo } from "@/components/v2/rooms/format";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { useTr } from "@/i18n/phrases";
import { v2Client } from "@/lib/v2/client";
import { roomsEmpty, unreadLabel } from "@/lib/v2/screens/rooms";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function RoomsSidebar({
  orgSlug,
  embedded = false,
}: {
  orgSlug: string;
  embedded?: boolean;
}) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const tr = useTr();
  const [rooms, setRooms] = useState<RoomInfo[]>([]);
  const [query, setQuery] = useState("");
  const [loadState, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const fetchNow = useCallback(() => {
    if (!orgId) return;
    v2Client()
      .rooms(orgId)
      .then((rows) => {
        const next = rows as RoomInfo[];
        setRooms(next);
        setState(roomsEmpty(next) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError(tr("Could not load rooms"));
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, tr]);

  // Until the workspace resolves, show its state. The first fetch starts in "loading"; setState runs only in callbacks.
  const state = orgState === "ready" ? loadState : orgState;

  const load = useCallback(() => {
    setState("loading");
    fetchNow();
  }, [fetchNow]);

  useEffect(() => {
    if (orgState === "ready") fetchNow();
  }, [orgState, fetchNow]);

  return (
    <aside
      className={embedded ? "px-3 pb-4" : "w-64 border-e border-[color:var(--fb-v2-border)] p-4"}
    >
      <div className="mb-2 flex items-center justify-between gap-2 px-2">
        <h2 className="text-xs font-medium text-[color:var(--fb-v2-text-muted)]">
          <Link href={`/w/${orgSlug}/rooms`} className="hover:underline">
            {tr("Rooms")}
          </Link>
        </h2>
        <Link
          href={`/w/${orgSlug}/rooms?new=dm`}
          className="text-xs text-[color:var(--fb-v2-accent)] hover:underline"
        >
          {tr("New message")}
        </Link>
      </div>
      <input
        className="v2-input mb-2 text-sm"
        aria-label={tr("Search rooms")}
        placeholder={tr("Search rooms")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ScreenBody
        state={state}
        error={error || orgError}
        emptyLabel={tr("No rooms yet")}
        onRetry={load}
      >
        <ul className="space-y-1">
          {rooms
            .filter(
              (room) =>
                !query.trim() || roomTitle(room).toLowerCase().includes(query.trim().toLowerCase())
            )
            .map((room) => (
              <li key={room.id}>
                <Link
                  href={`/w/${orgSlug}/rooms/${room.id}`}
                  className="flex items-center justify-between gap-2 rounded-lg px-2 py-1 text-sm hover:bg-[color:var(--fb-v2-border)]"
                >
                  <span>{roomTitle(room)}</span>
                  {unreadLabel(room.unread) ? (
                    <span className="text-xs text-[color:var(--fb-v2-accent)]">
                      {unreadLabel(room.unread)}
                    </span>
                  ) : null}
                </Link>
              </li>
            ))}
        </ul>
      </ScreenBody>
    </aside>
  );
}
