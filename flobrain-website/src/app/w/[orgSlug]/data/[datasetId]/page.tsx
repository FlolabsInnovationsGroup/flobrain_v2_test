"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { CardTile } from "@/components/v2/data/CardTile";
import { DataTable } from "@/components/v2/data/ResultChart";
import { ResultView } from "@/components/v2/data/ResultView";
import type { AskResult, Dataset, Table } from "@/components/v2/data/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

const TYPE_LABEL: Record<string, string> = { integer: "Number", real: "Decimal", boolean: "Yes/no", date: "Date", datetime: "Date and time", text: "Text" };

function Schema({ table }: { table: Table }) {
  const tr = useTr();
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-wrap gap-2" aria-label={tr("Columns")}>
        {table.columns.map((c) => (
          <li key={c.name} className="rounded-lg bg-[color:var(--fb-v2-raised)] px-2 py-1 text-xs">
            <span className="font-medium">{c.label || c.name}</span> <span className="text-[color:var(--fb-v2-text-muted)]">{tr(TYPE_LABEL[c.type] ?? "Text")}</span>
          </li>
        ))}
      </ul>
      {table.sample_rows.length ? <DataTable result={{ columns: table.columns.map((c) => c.name), rows: table.sample_rows }} caption={tr("Sample rows")} /> : null}
    </div>
  );
}

export default function DatasetPage() {
  const tr = useTr();
  const router = useRouter();
  const { orgSlug, datasetId } = useParams<{ orgSlug: string; datasetId: string }>();
  const { orgId, access } = useAccess();
  const { data, state, error, reload } = useOrgData<Dataset>(orgId, `/data/datasets/${datasetId}`);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<AskResult | null>(null);
  const [askError, setAskError] = useState<{ text: string; sql?: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || !orgId) return;
    setQuestion(q);
    setAsking(true);
    setAskError(null);
    setResult(null);
    try {
      setResult(await api.post<AskResult>(`/orgs/${orgId}/data/ask`, { dataset_id: datasetId, question: q }));
    } catch (err) {
      const e = err as { response?: { data?: { sql?: string } } };
      setAskError({ text: errorText(err), sql: e.response?.data?.sql });
    } finally {
      setAsking(false);
    }
  }

  async function save() {
    if (!result || !orgId) return;
    setSaving(true);
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/data/cards`, {
        dataset_id: datasetId,
        title: result.question.slice(0, 160),
        question: result.question,
        sql: result.sql,
        chart: result.chart,
        answer: result.answer,
      });
      setMessage({ kind: "ok", text: tr("Saved as a card. Add it to a report from the Reports tab.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setSaving(false);
    }
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const d = data;
  const suggestions = d ? suggestionsFor(d) : [];

  return (
    <div className="max-w-5xl">
      <p className="mb-2 text-sm">
        <Link href={`/w/${orgSlug}/data`} className="text-[color:var(--fb-v2-text-muted)] underline-offset-2 hover:underline">
          {tr("All data")}
        </Link>
      </p>
      <ScreenBody state={state} error={error} onRetry={reload}>
        {d ? (
          <>
            <PageHeader
              title={d.name}
              intro={d.description || undefined}
              action={
                d.can_manage ? (
                  <div className="flex flex-wrap gap-2">
                    {d.kind !== "upload" ? (
                      <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/data/datasets/${d.id}/refresh`), tr("Refreshed."))}>
                        {tr("Refresh")}
                      </Button>
                    ) : null}
                    <Button
                      variant="danger"
                      onClick={() => {
                        if (!window.confirm(tr("Delete this dataset, its copy of the data and its saved cards?"))) return;
                        void api.del(`/orgs/${orgId}/data/datasets/${d.id}`).then(
                          () => router.push(`/w/${orgSlug}/data`),
                          (err) => setMessage({ kind: "error", text: errorText(err) }),
                        );
                      }}
                    >
                      {tr("Delete")}
                    </Button>
                  </div>
                ) : null
              }
            />
            <div className="mb-6 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
              {d.status === "error" ? <Badge tone="bad">{tr("Needs attention")}</Badge> : <Badge tone="good">{tr("Ready")}</Badge>}
              <span>{tr({ upload: "Uploaded file", sheet: "Google Sheet", postgres: "PostgreSQL" }[d.kind])}</span>
              {d.source_name && d.kind === "upload" ? <span dir="ltr">{d.source_name}</span> : null}
              {d.connection ? (
                <code dir="ltr" className="rounded bg-[color:var(--fb-v2-raised)] px-1.5 py-0.5">
                  {d.connection}
                </code>
              ) : null}
              {d.last_refreshed_at ? <span>{tr("Updated {when}", { when: when(d.last_refreshed_at) })}</span> : null}
              {d.kind === "sheet" && d.next_refresh_at ? <span>{tr("Next refresh {when}", { when: when(d.next_refresh_at) })}</span> : null}
            </div>
            {d.status === "error" && d.last_error ? <Notice kind="error">{d.last_error}</Notice> : null}
            {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

            <Section title={tr("Ask a question")}>
              <form
                className="flex flex-col gap-2 sm:flex-row"
                onSubmit={(e) => {
                  e.preventDefault();
                  void ask(question);
                }}
              >
                <label className="sr-only" htmlFor="data-question">
                  {tr("Your question")}
                </label>
                <input
                  id="data-question"
                  className="v2-input min-w-0 flex-1"
                  maxLength={500}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={tr("For example: what changed this week?")}
                />
                <Button type="submit" disabled={asking || !question.trim()}>
                  {asking ? tr("Thinking…") : tr("Ask")}
                </Button>
              </form>
              {suggestions.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => void ask(s)}
                      className="rounded-full px-3 py-1 text-xs ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:bg-[color:var(--fb-v2-border)]"
                    >
                      {tr(s)}
                    </button>
                  ))}
                </div>
              ) : null}
              <p className="mt-2 text-xs text-[color:var(--fb-v2-text-faint)]">
                {tr("The AI writes one read-only query. FloBrain checks it, runs it on this dataset only and shows you the SQL.")}
              </p>
              <div className="mt-4">
                {askError ? (
                  <div className="flex flex-col gap-2">
                    <Notice kind="error">{askError.text}</Notice>
                    {askError.sql ? (
                      <pre dir="ltr" className="overflow-x-auto rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-xs">
                        {askError.sql}
                      </pre>
                    ) : null}
                  </div>
                ) : null}
                {result ? (
                  <ResultView
                    title={result.question}
                    answer={result.answer}
                    sql={result.sql}
                    chart={result.chart}
                    result={result}
                    rowCount={result.row_count}
                    onSave={save}
                    saving={saving}
                  />
                ) : null}
              </div>
            </Section>

            {d.cards?.length && orgId ? (
              <Section title={tr("Saved cards")}>
                <ul className="grid gap-4 lg:grid-cols-2">
                  {d.cards.map((c) => (
                    <CardTile key={c.id} orgId={orgId} card={c} canDelete={c.created_by === access?.user_id || !!d.can_manage} onChange={reload} />
                  ))}
                </ul>
              </Section>
            ) : null}

            <Section title={tr("What's in it")}>
              {d.tables.length > 1 ? (
                <div className="flex flex-col gap-3">
                  {d.tables.map((t) => (
                    <details key={t.name} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-3">
                      <summary className="cursor-pointer font-medium" dir="ltr">
                        {t.name}
                      </summary>
                      <div className="mt-3">
                        <Schema table={t} />
                      </div>
                    </details>
                  ))}
                </div>
              ) : d.tables[0] ? (
                <>
                  <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("{n} rows. Here are the columns and the first few rows.", { n: d.row_count.toLocaleString() })}</p>
                  <Schema table={d.tables[0]} />
                </>
              ) : (
                <Notice>{tr("No columns yet.")}</Notice>
              )}
            </Section>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}

/** A few starter questions from the column names. The English text is sent (it is what the demo
 * model understands); people see it in their language. */
function suggestionsFor(d: Dataset): string[] {
  const cols = new Set((d.tables[0]?.columns ?? []).map((c) => c.name));
  if (cols.has("signups") && cols.has("week")) return ["Sign-ups this week vs last", "Sign-ups by channel", "Sign-ups by week"];
  if (cols.has("status") && cols.has("priority")) return ["Tickets by status", "Average first response by priority", "Tickets by category"];
  if (cols.has("budgeted") && cols.has("spent")) return ["Budget left by category", "Which lines are over budget?", "Spent vs budget by category"];
  return ["How many rows are there?"];
}
