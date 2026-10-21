"use client";

import { useCallback, useState } from "react";

import { DocEditor } from "@/components/v2/docs/DocEditor";
import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import type { DocRow } from "@/lib/v2/screens/docs";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

/** A room's Docs tab: the list on the start side, the open document on the other. */
export function DocsScreen({
  orgSlug,
  roomId,
  initialDocId,
}: {
  orgSlug: string;
  roomId: string;
  initialDocId?: string;
}) {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const canWrite = has(access, "docs.write");
  const docs = useOrgData<DocRow[]>(orgId, `/rooms/${roomId}/docs`, { list: true });
  const [selectedId, setSelectedId] = useState<string | null>(initialDocId ?? null);
  const [filter, setFilter] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const rows = rowsOf<DocRow>(docs.data);
  const selected = rows.find((d) => d.id === selectedId) ?? rows[0] ?? null;
  const shown = filter.trim()
    ? rows.filter((d) => d.title.toLowerCase().includes(filter.trim().toLowerCase()))
    : rows;
  const { setData } = docs;
  const onSaved = useCallback(
    (saved: DocRow) =>
      setData((prev) =>
        rowsOf<DocRow>(prev).map((d) => (d.id === saved.id ? { ...d, ...saved } : d))
      ),
    [setData]
  );

  function open(id: string) {
    setSelectedId(id);
    setMessage(null);
    window.history.replaceState(null, "", `/w/${orgSlug}/rooms/${roomId}/docs/${id}`);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!orgId) return;
    setCreating(true);
    setMessage(null);
    try {
      const doc = await api.post<DocRow>(`/orgs/${orgId}/rooms/${roomId}/docs`, {
        title: newTitle.trim() || tr("Untitled"),
        content_text: "",
      });
      setData([...rows, doc].sort((a, b) => a.title.localeCompare(b.title)));
      setNewTitle("");
      open(doc.id);
      if (docs.state === "empty") docs.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setCreating(false);
    }
  }

  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">{tr("Docs")}</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="docs" />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
        <aside className="min-w-0">
          {canWrite ? (
            <form onSubmit={create} className="mb-3 flex gap-2">
              <label className="sr-only" htmlFor="new-doc-title">
                {tr("New document title")}
              </label>
              <input
                id="new-doc-title"
                className="v2-input"
                value={newTitle}
                maxLength={200}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder={tr("New document title")}
              />
              <Button type="submit" disabled={creating}>
                {tr("Create")}
              </Button>
            </form>
          ) : null}
          {rows.length > 6 ? (
            <input
              className="v2-input mb-2"
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={tr("Filter documents")}
              aria-label={tr("Filter documents")}
            />
          ) : null}
          <ScreenBody
            state={docs.state}
            error={docs.error || tr("Could not load docs")}
            emptyLabel={tr("No documents yet")}
            onRetry={docs.reload}
          >
            <ul className="space-y-1" aria-label={tr("Documents in this room")}>
              {shown.map((doc) => (
                <li key={doc.id}>
                  <button
                    type="button"
                    aria-current={selected?.id === doc.id ? "true" : undefined}
                    onClick={() => open(doc.id)}
                    className={cn(
                      "w-full rounded-lg px-3 py-2 text-start hover:bg-[color:var(--fb-v2-border)]",
                      selected?.id === doc.id &&
                        "bg-[color:var(--fb-v2-surface)] ring-1 ring-inset ring-[color:var(--fb-v2-border)]"
                    )}
                  >
                    <span className="block truncate font-medium">{doc.title}</span>
                    {doc.updated_at ? (
                      <span className="block truncate text-xs text-[color:var(--fb-v2-text-muted)]">
                        {tr("{when} by {name}", {
                          when: when(doc.updated_at),
                          name: doc.updated_by?.name ?? tr("someone"),
                        })}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
              {filter && !shown.length ? (
                <li className="px-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("No document matches.")}
                </li>
              ) : null}
            </ul>
          </ScreenBody>
        </aside>
        {orgId && selected && docs.state === "ready" ? (
          <DocEditor
            key={selected.id}
            orgId={orgId}
            doc={selected}
            canWrite={canWrite}
            onSaved={onSaved}
            onDeleted={(id) => {
              const rest = rows.filter((d) => d.id !== id);
              setData(rest);
              setSelectedId(rest[0]?.id ?? null);
              setMessage({ kind: "ok", text: tr("Document deleted.") });
              window.history.replaceState(null, "", `/w/${orgSlug}/rooms/${roomId}/docs`);
              if (!rest.length) docs.reload();
            }}
          />
        ) : null}
      </div>
    </section>
  );
}
