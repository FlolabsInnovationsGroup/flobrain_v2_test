"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { runStatusLabel, runTone, stepTypeLabel, type Run, type StepLogEntry } from "./types";

function stepTone(status: StepLogEntry["status"]): "waiting" | "good" | "bad" | "neutral" {
  if (status === "waiting") return "waiting";
  if (status === "done") return "good";
  if (status === "failed") return "bad";
  return "neutral";
}

function StepStatus({ status }: { status: StepLogEntry["status"] }) {
  const tr = useTr();
  const text =
    status === "waiting" ? tr("Waiting for approval") : status === "done" ? tr("Done") : status === "failed" ? tr("Failed") : status === "skipped" ? tr("Skipped") : tr("Started");
  return <Badge tone={stepTone(status)}>{text}</Badge>;
}

function reasonLabel(tr: (s: string) => string, reason: string): string {
  switch (reason) {
    case "manual":
      return tr("Run by hand");
    case "schedule":
      return tr("On schedule");
    case "webhook":
      return tr("From its webhook");
    case "task_blocked":
      return tr("A task was blocked");
    case "task_created":
      return tr("A task was created");
    case "room_message":
      return tr("A room message");
    case "meeting_ended":
      return tr("A meeting ended");
    case "customer_conversation":
      return tr("A customer conversation");
    default:
      return reason;
  }
}

/** Run history with a per-step log. Waiting runs are amber and link to Approvals. */
export function RunHistory({ runs, orgSlug }: { runs: Run[]; orgSlug: string }) {
  const tr = useTr();
  const [open, setOpen] = useState<string | null>(null);
  if (!runs.length) return <Notice>{tr("No runs yet.")}</Notice>;
  return (
    <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
      {runs.map((run) => {
        const expanded = open === run.id;
        const waiting = run.status === "waiting_approval";
        return (
          <li key={run.id} className={waiting ? "border-s-4 border-[color:var(--fb-v2-waiting)]" : ""}>
            <button
              type="button"
              className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-start focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]"
              aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : run.id)}
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{run.workflow_name}</span>
                <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">
                  {when(run.created_at)} · {reasonLabel(tr, run.reason)}
                  {run.triggered_by ? ` · ${run.triggered_by}` : ""}
                </span>
              </span>
              <Badge tone={runTone(run.status)}>{runStatusLabel(tr, run.status)}</Badge>
            </button>
            {expanded ? (
              <div className="px-4 pb-4">
                {waiting ? (
                  <p className="mb-3 text-sm">
                    <span className="text-[color:var(--fb-v2-waiting)]">{tr("Paused until the approval is decided.")}</span>{" "}
                    <Link href={`/w/${orgSlug}/approvals`} className="font-medium underline">
                      {tr("Open approvals")}
                    </Link>
                  </p>
                ) : null}
                {run.error ? <p className="mb-3 text-sm text-[color:var(--fb-v2-error)]">{run.error}</p> : null}
                <ol className="flex flex-col gap-2">
                  {(run.step_log ?? []).map((entry) => (
                    <li key={entry.step} className="rounded-lg border border-[color:var(--fb-v2-border)] p-3 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">
                          {tr("Step {n}: {name}", { n: entry.step, name: entry.label || stepTypeLabel(tr, entry.type) })}
                        </span>
                        <StepStatus status={entry.status} />
                      </div>
                      {entry.output ? <p className="mt-2 whitespace-pre-wrap text-[color:var(--fb-v2-text-muted)]" dir="auto">{entry.output}</p> : null}
                      {typeof entry.detail?.error === "string" ? <p className="mt-2 text-[color:var(--fb-v2-error)]">{entry.detail.error}</p> : null}
                    </li>
                  ))}
                </ol>
                {!(run.step_log ?? []).length ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No steps ran.")}</p> : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
