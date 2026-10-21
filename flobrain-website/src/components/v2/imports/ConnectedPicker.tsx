"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";

import { formatBytes } from "./logic";
import { RoomSelect } from "./RoomSelect";
import type { DriveFile, Meta, NotionPage, Run } from "./types";

type Row = { id: string; title: string; detail: string; disabled: string; type?: "page" | "database" };

/** Pick pages from a connected Notion, or files from a connected Google Drive, and import them into a room. */
export function ConnectedPicker({ orgId, meta, kind, onStarted }: { orgId: string; meta: Meta; kind: "notion" | "drive"; onStarted: (run: Run) => void }) {
  const tr = useTr();
  const [connection, setConnection] = useState(meta.notion[0]?.id ?? "");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [room, setRoom] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (kind === "notion" && !connection) return;
    let live = true;
    const path = kind === "notion" ? `/orgs/${orgId}/imports/notion/pages` : `/orgs/${orgId}/imports/drive/files`;
    const params: Record<string, string> = kind === "notion" ? { connection_id: connection, q: search } : { q: search };
    api
      .get<unknown>(path, params)
      .then((data) => {
        if (!live) return;
        setError("");
        if (kind === "notion") {
          setRows(
            rowsOf<NotionPage>(data).map((p) => ({ id: p.id, type: p.type, title: p.title, detail: p.type === "database" ? "Database" : "Page", disabled: "" })),
          );
        } else {
          const files = (data as { files?: DriveFile[] }).files ?? [];
          setRows(
            files.map((f) => ({
              id: f.id,
              title: f.name,
              detail: f.size ? formatBytes(f.size) : "",
              disabled: f.too_big ? "Too big" : !f.supported ? "PDF text needs a library this server does not have yet" : "",
            })),
          );
        }
      })
      .catch((err) => live && (setRows([]), setError(errorText(err))));
    return () => {
      live = false;
    };
  }, [orgId, kind, connection, search]);

  async function start() {
    setBusy(true);
    setError("");
    try {
      const picked = (rows ?? []).filter((r) => chosen.has(r.id));
      const run =
        kind === "notion"
          ? await api.post<Run>(`/orgs/${orgId}/imports/notion`, { connection_id: connection, room_id: room, items: picked.map((r) => ({ id: r.id, type: r.type })) })
          : await api.post<Run>(`/orgs/${orgId}/imports/drive`, { room_id: room, file_ids: picked.map((r) => r.id) });
      setChosen(new Set());
      onStarted(run);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {kind === "notion" && meta.notion.length > 1 ? (
        <label className="mb-3 block text-sm">
          <span className="mb-1 block font-medium">{tr("Notion connection")}</span>
          <select className="v2-input w-full sm:w-80" value={connection} onChange={(e) => setConnection(e.target.value)}>
            {meta.notion.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <form
        className="mb-3 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query.trim());
        }}
      >
        <input
          className="v2-input min-w-0 flex-1"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={kind === "notion" ? tr("Search pages") : tr("Search files")}
          aria-label={kind === "notion" ? tr("Search pages") : tr("Search files")}
        />
        <Button type="submit" variant="outline">
          {tr("Search")}
        </Button>
      </form>
      {rows === null ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Loading…")}</p> : null}
      {rows && !rows.length && !error ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Nothing found.")}</p> : null}
      {rows?.length ? (
        <ul className="mb-3 max-h-80 divide-y divide-[color:var(--fb-v2-border)] overflow-y-auto rounded-lg bg-[color:var(--fb-v2-raised)]">
          {rows.map((r) => (
            <li key={r.id} className="flex items-start gap-3 px-3 py-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                aria-label={r.title}
                disabled={!!r.disabled}
                checked={chosen.has(r.id)}
                onChange={(e) =>
                  setChosen((prev) => {
                    const next = new Set(prev);
                    if (e.target.checked) next.add(r.id);
                    else next.delete(r.id);
                    return next;
                  })
                }
              />
              <div className="min-w-0 flex-1">
                <p className="truncate">{r.title}</p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{r.detail ? tr(r.detail) : ""}</p>
                {r.disabled ? <p className="text-xs text-[color:var(--fb-v2-error)]">{tr(r.disabled)}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      <RoomSelect rooms={meta.rooms} value={room} onChange={setRoom} />
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="flex justify-end">
        <Button type="button" onClick={start} disabled={busy || !room || !chosen.size}>
          {tr("Import {n} documents", { n: chosen.size })}
        </Button>
      </div>
    </div>
  );
}
