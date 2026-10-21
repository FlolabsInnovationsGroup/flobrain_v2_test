"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { draftPayload, type CaseDraft, type Language } from "./evals";

type Doc = { id: string; title: string };

/**
 * One case. Keyboard: the question field has focus first, Ctrl or Cmd + Enter saves from any field,
 * Escape cancels. Lists are one phrase per line.
 */
export function CaseEditor({
  orgId,
  tools,
  initial,
  saveLabel,
  onSave,
  onCancel,
}: {
  orgId: string;
  tools: { key: string; label: string }[];
  initial: CaseDraft;
  saveLabel?: string;
  onSave: (body: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const tr = useTr();
  const id = useId();
  const [d, setD] = useState<CaseDraft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Doc[]>([]);
  const first = useRef<HTMLTextAreaElement>(null);

  useEffect(() => first.current?.focus(), []);

  useEffect(() => {
    const q = query.trim();
    if (!q) return;
    const timer = setTimeout(() => {
      api
        .get<Doc[]>(`/orgs/${orgId}/evals/documents`, { q })
        .then(setFound)
        .catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [orgId, query]);

  const set = <K extends keyof CaseDraft>(key: K, value: CaseDraft[K]) => setD((old) => ({ ...old, [key]: value }));

  async function save() {
    const out = draftPayload(d);
    if (!out.ok) {
      setError(
        out.error === "input"
          ? tr("Write the question the buddy should answer.")
          : out.error === "max_words"
            ? tr("Word limit must be a whole number from 1 to 5000.")
            : tr("An action can't be both expected and forbidden."),
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(out.body);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const field = "v2-input w-full";
  const label = "mb-1 block text-sm font-medium";
  const hint = "mt-1 block text-xs text-[color:var(--fb-v2-text-muted)]";

  return (
    <form
      className="flex flex-col gap-4 rounded-xl border border-[color:var(--fb-v2-border)] bg-[color:var(--fb-v2-surface)] p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          void save();
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
      }}
    >
      <div>
        <label className={label} htmlFor={`${id}-input`}>{tr("Question")}</label>
        <textarea ref={first} id={`${id}-input`} className={field} rows={3} maxLength={4000} required value={d.input} onChange={(e) => set("input", e.target.value)} />
        <span className={hint}>{tr("What a colleague would ask the buddy.")}</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className={label} htmlFor={`${id}-name`}>{tr("Short name")}</label>
          <input id={`${id}-name`} className={field} maxLength={120} value={d.name} onChange={(e) => set("name", e.target.value)} />
        </div>
        <div>
          <label className={label} htmlFor={`${id}-lang`}>{tr("Answer language")}</label>
          <select id={`${id}-lang`} className={field} value={d.language} onChange={(e) => set("language", e.target.value as Language)}>
            <option value="any">{tr("Any language")}</option>
            <option value="ar">{tr("Arabic")}</option>
            <option value="en">{tr("English")}</option>
          </select>
        </div>
      </div>

      <fieldset>
        <legend className={label}>{tr("Documents the buddy gets")}</legend>
        {d.docs.length ? (
          <ul className="mb-2 flex flex-wrap gap-2">
            {d.docs.map((doc) => (
              <li key={doc.id} className="inline-flex items-center gap-1 rounded-full bg-[color:var(--fb-v2-border)] py-0.5 ps-3 pe-1 text-sm">
                {doc.title || tr("A document you can't open")}
                <button
                  type="button"
                  className="rounded-full px-1.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]"
                  aria-label={tr("Remove {name}", { name: doc.title || tr("document") })}
                  onClick={() => set("docs", d.docs.filter((x) => x.id !== doc.id))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {d.docs.length < 5 ? (
          <>
            <input
              className={field}
              type="search"
              placeholder={tr("Search your documents")}
              aria-label={tr("Search your documents")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query.trim() && found.length ? (
              <ul className="mt-1 max-h-40 overflow-auto rounded-lg border border-[color:var(--fb-v2-border)]">
                {found
                  .filter((f) => !d.docs.some((x) => x.id === f.id))
                  .map((f) => (
                    <li key={f.id}>
                      <button
                        type="button"
                        className="w-full px-3 py-1.5 text-start text-sm hover:bg-[color:var(--fb-v2-border)] focus-visible:bg-[color:var(--fb-v2-border)] focus-visible:outline-none"
                        onClick={() => {
                          set("docs", [...d.docs, f]);
                          setQuery("");
                        }}
                      >
                        {f.title}
                      </button>
                    </li>
                  ))}
              </ul>
            ) : null}
          </>
        ) : null}
        <span className={hint}>{tr("Evals don't search the workspace. The buddy reads only these, so every run is the same test.")}</span>
      </fieldset>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className={label} htmlFor={`${id}-inc`}>{tr("Must say")}</label>
          <textarea id={`${id}-inc`} className={field} rows={3} value={d.mustInclude} onChange={(e) => set("mustInclude", e.target.value)} />
          <span className={hint}>{tr("One phrase per line. Not case sensitive.")}</span>
        </div>
        <div>
          <label className={label} htmlFor={`${id}-exc`}>{tr("Must not say")}</label>
          <textarea id={`${id}-exc`} className={field} rows={3} value={d.mustNotInclude} onChange={(e) => set("mustNotInclude", e.target.value)} />
          <span className={hint}>{tr("One phrase per line.")}</span>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <label className={label} htmlFor={`${id}-tool`}>{tr("Expected action")}</label>
          <select id={`${id}-tool`} className={field} value={d.expectedTool} onChange={(e) => set("expectedTool", e.target.value)}>
            <option value="">{tr("Don't check")}</option>
            <option value="none">{tr("No action")}</option>
            {tools.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={label} htmlFor={`${id}-words`}>{tr("Word limit")}</label>
          <input id={`${id}-words`} className={field} inputMode="numeric" value={d.maxWords} onChange={(e) => set("maxWords", e.target.value)} placeholder={tr("No limit")} />
        </div>
        <label className="flex items-center gap-2 self-end pb-2 text-sm">
          <input type="checkbox" checked={d.mustCite} onChange={(e) => set("mustCite", e.target.checked)} />
          {tr("Must cite a source")}
        </label>
      </div>

      <details>
        <summary className="cursor-pointer text-sm font-medium">{tr("Forbidden actions ({n})", { n: d.forbiddenTools.length })}</summary>
        <div className="mt-2 grid max-h-48 gap-1 overflow-auto sm:grid-cols-2">
          {tools.map((t) => (
            <label key={t.key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={d.forbiddenTools.includes(t.key)}
                onChange={(e) => set("forbiddenTools", e.target.checked ? [...d.forbiddenTools, t.key] : d.forbiddenTools.filter((k) => k !== t.key))}
              />
              {t.label}
            </label>
          ))}
        </div>
      </details>

      <div>
        <label className={label} htmlFor={`${id}-rubric`}>{tr("What a good answer does (AI judge)")}</label>
        <textarea id={`${id}-rubric`} className={field} rows={2} maxLength={2000} value={d.rubric} onChange={(e) => set("rubric", e.target.value)} />
        <span className={hint}>{tr("Optional. An AI judge scores the answer from 1 to 5 against this; 3 or more passes.")}</span>
      </div>

      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={busy}>
          {saveLabel ?? tr("Save case")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {tr("Cancel")}
        </Button>
        <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Ctrl or Cmd + Enter saves. Esc cancels.")}</span>
      </div>
    </form>
  );
}
