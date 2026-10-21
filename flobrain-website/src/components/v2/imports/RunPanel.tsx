"use client";

import { Button } from "@/components/v2/ui/button";
import { Badge, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { countLines, percent, SOURCE_LABEL, STATUS_LABEL, statusTone } from "./logic";
import { ProgressBar } from "./ProgressBar";
import type { Run } from "./types";

/** Step 3: live progress of the import that is running, with a stop button. */
export function RunPanel({ run, onCancel, busy }: { run: Run; onCancel: () => void; busy: boolean }) {
  const tr = useTr();
  const value = run.status === "analyzing" || run.status === "undoing" ? null : percent(run);
  const label = run.status === "analyzing" ? tr("Checking the file") : run.status === "undoing" ? tr("Removing what this import added") : tr("Importing");
  return (
    <Section title={tr(SOURCE_LABEL[run.source])} aside={<Badge tone={statusTone(run.status)}>{tr(STATUS_LABEL[run.status])}</Badge>}>
      <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" aria-live="polite">
        <ProgressBar value={value} label={label} />
        <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
          {run.progress?.total ? tr("{m} of {n}", { m: (run.progress.done ?? 0).toLocaleString(), n: run.progress.total.toLocaleString() }) : ""}
          {run.progress?.current ? ` · ${run.progress.current}` : ""}
        </p>
        {countLines(run.counts).length ? (
          <p className="mt-1 text-sm">{countLines(run.counts).map((c) => tr(c.template, { n: c.n.toLocaleString() })).join(" · ")}</p>
        ) : null}
        <p className="mt-2 text-xs text-[color:var(--fb-v2-text-faint)]">{tr("You can leave this page. We will send you a notification when it is done.")}</p>
        {run.status !== "undoing" ? (
          <div className="mt-3 flex justify-end">
            <Button type="button" variant="danger" onClick={onCancel} disabled={busy || run.cancel_requested}>
              {run.cancel_requested ? tr("Stopping…") : tr("Stop")}
            </Button>
          </div>
        ) : null}
      </div>
    </Section>
  );
}
