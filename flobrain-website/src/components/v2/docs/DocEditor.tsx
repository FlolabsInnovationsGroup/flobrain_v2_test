"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { ConflictPanel, type ConflictChoice } from "@/components/v2/docs/ConflictPanel";
import { DocAttachments } from "@/components/v2/docs/DocAttachments";
import { DocHistory } from "@/components/v2/docs/DocHistory";
import { Button } from "@/components/v2/ui/button";
import { Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiError, errorText } from "@/lib/v2/api";
import {
  applyMarkup,
  backupState,
  isDirty,
  readBackup,
  savePayload,
  writeBackup,
  type DocRow,
  type Markup,
} from "@/lib/v2/screens/docs";
import { cn } from "@/lib/utils";

const AUTOSAVE_MS = 1200;
const RETRY_MS = 5000;

type Conflict = { theirs: DocRow; mine: { title: string; text: string } };

function currentOf(err: unknown): DocRow | undefined {
  return (err as { response?: { data?: { current?: DocRow } } }).response?.data?.current;
}

/**
 * One document: title, Markdown body with a small toolbar and preview, autosave (debounced,
 * "Saved" when the server has it), conflicts that keep the draft, history and attachments.
 * Keyed by document id by the parent, so its state starts fresh per document.
 */
export function DocEditor({
  orgId,
  doc,
  canWrite,
  onSaved,
  onDeleted,
}: {
  orgId: string;
  doc: DocRow;
  canWrite: boolean;
  onSaved: (doc: DocRow) => void;
  onDeleted: (docId: string) => void;
}) {
  const tr = useTr();
  // A draft left in this browser (failed save, closed tab) comes back, or opens a conflict.
  const [start] = useState(() => {
    const backup = canWrite ? readBackup(doc.id) : null;
    return { backup, state: backupState(doc, backup) };
  });
  const [base, setBase] = useState<DocRow>(doc);
  const [title, setTitle] = useState(
    start.state === "restore" && start.backup ? start.backup.title : doc.title
  );
  const [text, setText] = useState(
    start.state !== "none" && start.backup ? start.backup.text : doc.content_text
  );
  const [conflict, setConflict] = useState<Conflict | null>(
    start.state === "conflict" && start.backup
      ? { theirs: doc, mine: { title: start.backup.title, text: start.backup.text } }
      : null
  );
  const [aside, setAside] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ text: string; retry: boolean } | null>(null);
  const [mode, setMode] = useState<"write" | "preview" | "history">("write");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [notice, setNotice] = useState<string | null>(
    start.state === "restore" ? tr("Restored your unsaved draft from this browser.") : null
  );
  const area = useRef<HTMLTextAreaElement>(null);

  const dirty = canWrite && isDirty(base, title, text);
  const titleBlank = title.trim() === "";

  const save = useCallback(() => {
    if (!canWrite) return;
    const sent = { title, text };
    setSaving(true);
    api
      .patch<DocRow>(`/orgs/${orgId}/docs/${doc.id}`, savePayload(base, title, text))
      .then((saved) => {
        setBase(saved);
        setSaving(false);
        setError(null);
        onSaved(saved);
      })
      .catch((err) => {
        setSaving(false);
        const { status } = apiError(err);
        const current = currentOf(err);
        if (status === 409 && current) {
          if (
            current.content_text === sent.text &&
            (sent.title.trim() === "" || sent.title.trim() === current.title)
          ) {
            setBase(current); // the server already has exactly this
            return;
          }
          setConflict({ theirs: current, mine: sent });
          return;
        }
        // Network and server errors retry on their own; a refused save waits for the next edit.
        setError({ text: errorText(err), retry: status === 0 || status === 429 || status >= 500 });
      });
  }, [canWrite, orgId, doc.id, base, title, text, onSaved]);

  // Autosave: wait for a pause in typing, never while a save runs or a conflict is open.
  // After a failed save, wait longer before the next try.
  useEffect(() => {
    if (!dirty || conflict || saving || (error && !error.retry)) return;
    const timer = window.setTimeout(save, error ? RETRY_MS : AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [dirty, conflict, saving, error, save]);

  function edit(next: { title?: string; text?: string }) {
    if (next.title !== undefined) setTitle(next.title);
    if (next.text !== undefined) setText(next.text);
    if (error && !error.retry) setError(null); // an edit is a new attempt
  }

  // Keep the draft in this browser until the server has it.
  useEffect(() => {
    if (!canWrite) return;
    if (dirty || conflict) {
      const mine = conflict ? conflict.mine : { title, text };
      // The version the draft started from: a reload with a newer server copy reopens the conflict.
      writeBackup(doc.id, {
        version: base.version,
        title: mine.title,
        text: mine.text,
        at: new Date().toISOString(),
      });
    } else if (aside !== null) {
      writeBackup(doc.id, {
        version: base.version,
        title,
        text: aside,
        at: new Date().toISOString(),
      });
    } else {
      writeBackup(doc.id, null);
    }
  }, [canWrite, dirty, conflict, aside, base.version, title, text, doc.id]);

  // Leaving with unsaved changes: ask the browser to confirm, and send what we have.
  const latest = useRef({ dirty, conflict, payload: savePayload(base, title, text) });
  useEffect(() => {
    latest.current = { dirty, conflict, payload: savePayload(base, title, text) };
  });
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    const box = latest;
    const id = doc.id;
    return () => {
      const last = box.current;
      if (!last.dirty || last.conflict) return;
      api
        .patch(`/orgs/${orgId}/docs/${id}`, last.payload)
        .then(() => writeBackup(id, null))
        .catch(() => undefined); // the browser copy stays; it comes back next time
    };
  }, [orgId, doc.id]);

  function choose(choice: ConflictChoice) {
    if (!conflict) return;
    const { theirs, mine } = conflict;
    setBase(theirs);
    setConflict(null);
    setError(null);
    if (choice === "mine") {
      setTitle(mine.title.trim() ? mine.title : theirs.title);
      setText(mine.text); // stays dirty: autosave sends it on top of their version
    } else if (choice === "merge") {
      setTitle(theirs.title);
      setText(theirs.content_text);
      setAside(mine.text);
      setMode("write");
    } else {
      setTitle(theirs.title);
      setText(theirs.content_text);
    }
    onSaved(theirs);
  }

  function markup(kind: Markup) {
    const el = area.current;
    if (!el) return;
    const next = applyMarkup(text, el.selectionStart, el.selectionEnd, kind);
    edit({ text: next.text });
    window.requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(next.start, next.end);
    });
  }

  async function remove() {
    try {
      await api.del(`/orgs/${orgId}/docs/${doc.id}`);
      writeBackup(doc.id, null);
      onDeleted(doc.id);
    } catch (err) {
      setConfirmDelete(false);
      setNotice(errorText(err));
    }
  }

  const status = !canWrite
    ? tr("Read only")
    : conflict
      ? tr("Not saved yet")
      : saving
        ? tr("Saving…")
        : error
          ? error.retry
            ? tr("Couldn't save. Trying again…")
            : tr("Not saved: {error}", { error: error.text })
          : dirty
            ? tr("Unsaved changes")
            : tr("Saved");
  const editedBy = base.updated_by?.name ?? base.created_by?.name;

  return (
    <article className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <label className="sr-only" htmlFor={`title-${doc.id}`}>
            {tr("Title")}
          </label>
          <input
            id={`title-${doc.id}`}
            className="w-full bg-transparent text-xl font-semibold outline-none focus:underline"
            value={title}
            readOnly={!canWrite}
            maxLength={200}
            onChange={(e) => edit({ title: e.target.value })}
            placeholder={tr("Untitled")}
          />
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {editedBy
              ? tr("Version {n}. Last edited {when} by {name}.", {
                  n: base.version,
                  when: when(base.updated_at),
                  name: editedBy,
                })
              : null}
            {titleBlank && canWrite
              ? ` ${tr("A document needs a title. The old one is kept until you type one.")}`
              : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            role="status"
            aria-live="polite"
            className={cn(
              "text-sm",
              error && !error.retry
                ? "text-[color:var(--fb-v2-error)]"
                : "text-[color:var(--fb-v2-text-muted)]"
            )}
          >
            {status}
          </span>
          {error && !error.retry ? (
            <Button type="button" variant="outline" onClick={() => setError(null)}>
              {tr("Try again")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant={mode === "history" ? "default" : "outline"}
            onClick={() => setMode(mode === "history" ? "write" : "history")}
          >
            {tr("History")}
          </Button>
          {base.can_delete ? (
            <Button type="button" variant="danger" onClick={() => setConfirmDelete(true)}>
              {tr("Delete")}
            </Button>
          ) : null}
        </div>
      </div>

      {confirmDelete ? (
        <div
          role="alertdialog"
          aria-label={tr("Delete this document?")}
          className="mt-3 flex flex-wrap items-center gap-2 rounded-xl p-3 ring-1 ring-inset ring-[color:var(--fb-v2-error)]"
        >
          <span className="text-sm">
            {tr("Delete “{title}” and its history and files? This can't be undone.", {
              title: base.title,
            })}
          </span>
          <Button type="button" variant="danger" onClick={() => void remove()}>
            {tr("Delete document")}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setConfirmDelete(false)}>
            {tr("Cancel")}
          </Button>
        </div>
      ) : null}
      {notice ? <Notice>{notice}</Notice> : null}

      <div className="mt-4">
        {conflict ? (
          <ConflictPanel mine={conflict.mine} theirs={conflict.theirs} onChoose={choose} />
        ) : null}
        {mode === "history" ? (
          <DocHistory
            orgId={orgId}
            doc={base}
            canRestore={canWrite && !dirty && !conflict && !saving}
            blockedReason={
              canWrite
                ? tr("Wait until your changes are saved, then restore.")
                : tr("You can read this document but not change it.")
            }
            onClose={() => setMode("write")}
            onConflict={(current) => {
              // Restore only runs with nothing unsaved, so showing the newer copy loses nothing.
              setBase(current);
              setTitle(current.title);
              setText(current.content_text);
              setNotice(
                tr(
                  "Someone saved a newer version. It is shown now. Restore again if you still want the older one."
                )
              );
              onSaved(current);
            }}
            onRestored={(restored) => {
              setBase(restored);
              setTitle(restored.title);
              setText(restored.content_text);
              setNotice(tr("Restored. It is now version {n}.", { n: restored.version }));
              setMode("write");
              onSaved(restored);
            }}
          />
        ) : conflict ? null : (
          <>
            <div
              className="mb-2 flex flex-wrap items-center gap-1"
              role="toolbar"
              aria-label={tr("Formatting")}
            >
              <div role="tablist" className="me-3 flex gap-1">
                {(["write", "preview"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="tab"
                    aria-selected={mode === m}
                    onClick={() => setMode(m)}
                    className={cn(
                      "rounded-md px-2 py-1 text-sm",
                      mode === m
                        ? "bg-[color:var(--fb-v2-border)] font-medium"
                        : "text-[color:var(--fb-v2-text-muted)]"
                    )}
                  >
                    {m === "write" ? tr("Write") : tr("Preview")}
                  </button>
                ))}
              </div>
              {canWrite && mode === "write"
                ? (
                    [
                      ["heading", tr("Heading"), "H"],
                      ["bold", tr("Bold"), "B"],
                      ["italic", tr("Italic"), "I"],
                      ["list", tr("Bulleted list"), "•"],
                      ["check", tr("Checklist"), "☐"],
                      ["link", tr("Link"), "🔗"],
                      ["code", tr("Code"), "</>"],
                    ] as const
                  ).map(([kind, label, glyph]) => (
                    <button
                      key={kind}
                      type="button"
                      title={label}
                      aria-label={label}
                      onClick={() => markup(kind)}
                      className="min-w-8 rounded-md px-2 py-1 text-sm hover:bg-[color:var(--fb-v2-border)]"
                    >
                      <span
                        aria-hidden
                        className={
                          kind === "bold" ? "font-bold" : kind === "italic" ? "italic" : ""
                        }
                      >
                        {glyph}
                      </span>
                    </button>
                  ))
                : null}
            </div>
            {mode === "write" ? (
              <div className={aside !== null ? "grid gap-3 lg:grid-cols-2" : ""}>
                <textarea
                  ref={area}
                  aria-label={tr("Document text")}
                  className="min-h-[24rem] w-full resize-y rounded-[length:var(--fb-v2-radius)] bg-transparent p-3 font-mono text-sm leading-6 ring-1 ring-inset ring-[color:var(--fb-v2-border)] focus:outline-none focus:ring-[color:var(--fb-v2-accent)]"
                  value={text}
                  readOnly={!canWrite}
                  placeholder={
                    canWrite
                      ? tr("Start writing. Markdown works: # heading, **bold**, - list.")
                      : ""
                  }
                  onChange={(e) => edit({ text: e.target.value })}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
                      e.preventDefault();
                      if (dirty && !saving && !conflict) save();
                    }
                  }}
                />
                {aside !== null ? (
                  <aside
                    className="min-w-0 rounded-[length:var(--fb-v2-radius)] p-3 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]"
                    aria-label={tr("Your earlier draft")}
                  >
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium">
                        {tr("Your earlier draft. Copy what you need into the document.")}
                      </p>
                      <div className="flex gap-1">
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() =>
                            void navigator.clipboard?.writeText(aside).catch(() => undefined)
                          }
                        >
                          {tr("Copy")}
                        </Button>
                        <Button type="button" variant="ghost" onClick={() => setAside(null)}>
                          {tr("Done")}
                        </Button>
                      </div>
                    </div>
                    <pre className="max-h-[22rem] overflow-auto whitespace-pre-wrap text-sm">
                      {aside}
                    </pre>
                  </aside>
                ) : null}
              </div>
            ) : (
              <div className="min-h-[24rem] rounded-[length:var(--fb-v2-radius)] p-3 text-sm leading-6 ring-1 ring-inset ring-[color:var(--fb-v2-border)] [&_a]:underline [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:text-lg [&_h2]:font-semibold [&_code]:rounded [&_code]:bg-[color:var(--fb-v2-border)] [&_code]:px-1 [&_li]:ms-5 [&_ol]:list-decimal [&_p]:my-2 [&_pre]:overflow-auto [&_ul]:list-disc">
                {text.trim() ? (
                  <ReactMarkdown
                    components={{
                      a: ({ href, children }) => (
                        <a href={href} target="_blank" rel="noopener noreferrer">
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {text}
                  </ReactMarkdown>
                ) : (
                  <p className="text-[color:var(--fb-v2-text-muted)]">
                    {tr("Nothing to preview yet.")}
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
      <DocAttachments orgId={orgId} docId={doc.id} canWrite={canWrite} />
    </article>
  );
}
