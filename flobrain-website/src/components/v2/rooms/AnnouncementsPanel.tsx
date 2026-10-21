"use client";

import { useCallback, useEffect, useState } from "react";

import { roomTime } from "@/components/v2/rooms/format";
import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

type Announcement = { id: string; body: string; pinned: boolean; author_name?: string | null; created_at: string };

/** Pinned announcements for one room. People with "Pin announcements" can post, pin and unpin. */
export function AnnouncementsPanel({ orgId, roomId, canManage }: { orgId: string; roomId: string; canManage: boolean }) {
  const tr = useTr();
  const [rows, setRows] = useState<Announcement[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [writing, setWriting] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const fetchNow = useCallback(() => {
    const params: Record<string, string> = { room: roomId };
    if (canManage && showAll) params.include_unpinned = "1";
    api
      .get<Announcement[]>(`/orgs/${orgId}/announcements`, params)
      .then(setRows)
      .catch((err) => setError(errorText(err)));
  }, [orgId, roomId, canManage, showAll]);

  useEffect(fetchNow, [fetchNow]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await run();
      fetchNow();
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (!rows.length && !canManage) return null;

  return (
    <section aria-label={tr("Announcements")} className="mb-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{tr("Announcements")}</h2>
        {canManage ? (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="ghost" onClick={() => setShowAll((v) => !v)}>
              {showAll ? tr("Pinned only") : tr("Show unpinned too")}
            </Button>
            <Button type="button" variant="outline" onClick={() => setWriting((v) => !v)}>
              {tr("New announcement")}
            </Button>
          </div>
        ) : null}
      </div>
      {writing ? (
        <form
          className="mb-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!draft.trim()) return;
            const ok = await act(() => api.post(`/orgs/${orgId}/announcements`, { room: roomId, body: draft.trim() }));
            if (ok) {
              setDraft("");
              setWriting(false);
            }
          }}
        >
          <input
            className="v2-input"
            value={draft}
            maxLength={8000}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={tr("What should everyone in this room know?")}
            aria-label={tr("Announcement")}
          />
          <Button type="submit" disabled={busy || !draft.trim()}>
            {tr("Pin it")}
          </Button>
        </form>
      ) : null}
      {rows.length === 0 ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No pinned announcements")}</p> : null}
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-start justify-between gap-2 border-s-2 border-[color:var(--fb-v2-accent)] ps-3">
            <div className="min-w-0 flex-1">
              <p className="whitespace-pre-wrap text-sm">{row.body}</p>
              <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                {row.author_name ? `${row.author_name} · ` : ""}
                {roomTime(row.created_at, tr)}
                {row.pinned ? "" : ` · ${tr("Unpinned")}`}
              </p>
            </div>
            {canManage ? (
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => act(() => api.post(`/orgs/${orgId}/announcements/${row.id}/${row.pinned ? "unpin" : "pin"}`))}
              >
                {row.pinned ? tr("Unpin") : tr("Pin")}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  );
}
