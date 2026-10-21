"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { ResultChart } from "./ResultChart";
import type { ChartSpec, Result } from "./types";

/** The SQL that produced an answer, folded by default, with a copy button. */
export function SqlBlock({ sql }: { sql: string }) {
  const tr = useTr();
  const [copied, setCopied] = useState(false);
  if (!sql) return null;
  return (
    <details className="rounded-lg border border-[color:var(--fb-v2-border)] text-sm">
      <summary className="cursor-pointer px-3 py-2 text-[color:var(--fb-v2-text-muted)]">{tr("SQL used")}</summary>
      <div className="border-t border-[color:var(--fb-v2-border)] p-3">
        <pre dir="ltr" className="overflow-x-auto whitespace-pre-wrap break-words font-[family-name:var(--fb-v2-font-mono)] text-xs">
          {sql}
        </pre>
        <Button
          variant="outline"
          className="mt-2 text-xs"
          onClick={() => {
            void navigator.clipboard?.writeText(sql).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          {copied ? tr("Copied") : tr("Copy SQL")}
        </Button>
      </div>
    </details>
  );
}

type Props = {
  title: string;
  answer: string;
  sql: string;
  chart: ChartSpec;
  result: Result;
  rowCount?: number;
  onSave?: () => void;
  saving?: boolean;
};

export function ResultView({ title, answer, sql, chart, result, rowCount, onSave, saving }: Props) {
  const tr = useTr();
  return (
    <section className="flex flex-col gap-3" aria-live="polite">
      {answer ? <p className="text-base leading-relaxed">{answer}</p> : null}
      {sql ? <ResultChart spec={chart} result={result} title={title} /> : null}
      {result.truncated ? (
        <Notice>{tr("Only the first {n} rows came back. Ask a narrower question for the rest.", { n: rowCount ?? result.rows.length })}</Notice>
      ) : null}
      <SqlBlock sql={sql} />
      {onSave && sql ? (
        <div>
          <Button variant="outline" onClick={onSave} disabled={saving}>
            {saving ? tr("Saving…") : tr("Save as card")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
