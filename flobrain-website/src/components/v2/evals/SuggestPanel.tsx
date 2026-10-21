"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { CaseEditor } from "./CaseEditor";
import { checkCount, draftFrom, draftPayload, type EvalCase } from "./evals";

type Suggestion = Omit<EvalCase, "id" | "set" | "position" | "context_docs"> & { keep: boolean };

/** Ask the AI for draft cases, review and edit them, then save the ones you keep. Nothing is saved before. */
export function SuggestPanel({
  orgId,
  setId,
  tools,
  onSaved,
  onClose,
}: {
  orgId: string;
  setId: string;
  tools: { key: string; label: string }[];
  onSaved: (n: number) => void;
  onClose: () => void;
}) {
  const tr = useTr();
  const [items, setItems] = useState<Suggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      const out = await api.post<{ cases: Partial<Omit<Suggestion, "keep">>[] }>(`/orgs/${orgId}/evals/sets/${setId}/suggest`);
      setItems(out.cases.map((c) => ({
        name: "", must_include: [], must_not_include: [], must_cite: false, expected_tool: "", forbidden_tools: [],
        max_words: null, language: "any", rubric: "", context_doc_ids: [], ...c, input: c.input ?? "", keep: true,
      })));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveKept() {
    if (!items) return;
    const kept = items.filter((i) => i.keep);
    const bodies = kept.map((c) => draftPayload(draftFrom(c))).flatMap((p) => (p.ok ? [p.body] : []));
    if (!bodies.length) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/orgs/${orgId}/evals/sets/${setId}/cases`, { cases: bodies });
      onSaved(bodies.length);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const kept = items?.filter((i) => i.keep).length ?? 0;
  return (
    <section className="rounded-xl border border-[color:var(--fb-v2-border)] p-4" aria-label={tr("Suggested cases")}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">{tr("Suggest cases")}</h3>
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("The AI drafts questions from the buddy's description, its starter prompts and why people marked answers not helpful (reasons only, never their messages). You choose what to keep.")}
          </p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          {tr("Close")}
        </Button>
      </div>
      {!items ? (
        <Button onClick={() => void ask()} disabled={busy}>
          {busy ? tr("Drafting…") : tr("Draft cases")}
        </Button>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {items.map((c, i) =>
              editing === i ? (
                <li key={i}>
                  <CaseEditor
                    orgId={orgId}
                    tools={tools}
                    initial={draftFrom(c)}
                    saveLabel={tr("Keep these changes")}
                    onCancel={() => setEditing(null)}
                    onSave={async (body) => {
                      setItems((all) => (all ?? []).map((x, j) => (j === i ? ({ ...x, ...(body as Partial<Suggestion>), keep: true }) : x)));
                      setEditing(null);
                    }}
                  />
                </li>
              ) : (
                <li key={i} className="flex items-start gap-3 rounded-lg bg-[color:var(--fb-v2-surface)] p-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={c.keep}
                    aria-label={tr("Keep “{q}”", { q: c.input })}
                    onChange={(e) => setItems((all) => (all ?? []).map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)))}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium" dir="auto">{c.name || c.input}</p>
                    {c.name ? <p className="text-sm" dir="auto">{c.input}</p> : null}
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {tr("{n} checks", { n: checkCount(c) })}
                      {c.rubric ? ` · ${c.rubric}` : ""}
                    </p>
                  </div>
                  <Button variant="ghost" onClick={() => setEditing(i)}>
                    {tr("Edit")}
                  </Button>
                </li>
              ),
            )}
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={() => void saveKept()} disabled={busy || !kept}>
              {tr("Save {n} cases", { n: kept })}
            </Button>
            <Button variant="outline" onClick={() => void ask()} disabled={busy}>
              {tr("Draft again")}
            </Button>
          </div>
        </>
      )}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  );
}
