"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Notice, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { countBy, logBadge, type LogRow } from "./connectors";

const FILTERS = [
  ["", "All"],
  ["waiting", "Waiting for approval"],
  ["done", "Done"],
  ["failed", "Failed"],
] as const;

const focusRing = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fb-v2-accent)]";

export function ActionLog({ rows, slug }: { rows: LogRow[]; slug: string }) {
  const tr = useTr();
  const [filter, setFilter] = useState<string>("");
  const counts = countBy(rows);
  const shown = filter ? rows.filter((r) => r.state === filter) : rows;
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label={tr("Filter actions")}>
        {FILTERS.map(([key, label]) => (
          <button
            key={key || "all"}
            type="button"
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
            className={`rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] ${focusRing} ${
              filter === key ? "bg-[color:var(--fb-v2-accent-soft)] font-medium" : "hover:bg-[color:var(--fb-v2-border)]"
            }`}
          >
            {tr(label)} {key ? <span className="text-[color:var(--fb-v2-text-muted)]">{counts[key] ?? 0}</span> : null}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <Notice>{rows.length ? tr("No actions in this view.") : tr("No write actions yet. Ask a buddy, for example: create a Jira issue for the login bug.")}</Notice>
      ) : (
        <Rows>
          {shown.map((r) => {
            const badge = logBadge(r.state);
            return (
              <Row key={r.id} className="items-start">
                <div className="min-w-0 flex-1 basis-64">
                  <p className="break-words font-medium">{r.summary || tr(r.label)}</p>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {[r.provider_name, r.by, when(r.created_at)].filter(Boolean).join(" · ")}
                  </p>
                  {r.state === "failed" && r.error ? (
                    <p className="mt-1 text-sm text-[color:var(--fb-v2-error)]">{r.error}</p>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {r.simulated ? <Badge>{tr("Simulated")}</Badge> : null}
                  <Badge tone={badge.tone}>{tr(badge.label)}</Badge>
                  {r.state === "waiting" ? (
                    <Link className={`rounded text-sm font-medium underline-offset-2 hover:underline ${focusRing}`} href={`/w/${slug}/approvals`}>
                      {tr("Review")}
                    </Link>
                  ) : null}
                  {r.url ? (
                    <a className={`rounded text-sm font-medium underline-offset-2 hover:underline ${focusRing}`} href={r.url} target="_blank" rel="noreferrer noopener">
                      {tr("Open")}
                    </a>
                  ) : null}
                </div>
              </Row>
            );
          })}
        </Rows>
      )}
    </div>
  );
}
