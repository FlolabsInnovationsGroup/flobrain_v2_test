"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { ApprovalQueue } from "@/components/v2/timer/ApprovalQueue";
import { Breakdown } from "@/components/v2/timer/Breakdown";
import { EntryForm, type EntryBody } from "@/components/v2/timer/EntryForm";
import { TIMER_EVENT } from "@/components/v2/timer/TopBarTimer";
import { WeekPicker } from "@/components/v2/timer/WeekPicker";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { isLead } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import {
  approvalLabel,
  approvalTone,
  categoryLabel,
  formatDuration,
  mondayOf,
  type TimeEntryRow,
} from "@/lib/v2/screens/time";
import { useOrgData } from "@/lib/v2/useOrgData";

type Report = {
  seconds: number;
  entries: number;
  by_category: Array<{ key: string; seconds: number }>;
  by_project: Array<{ id: string | null; name: string; seconds: number }>;
};
type Option = { id: string; name: string };

export function TimeScreen({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const [week, setWeek] = useState(() => mondayOf(new Date()));
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const reviewer = isLead(access) || access?.org_role === "owner" || access?.org_role === "admin";

  const entries = useOrgData<{ results: TimeEntryRow[] }>(orgId, `/time-entries?week=${week}&page_size=100`);
  const report = useOrgData<Report>(orgId, `/time-reports/me?week=${week}`);
  const tasks = useOrgData<{ results: Array<{ id: string; title: string; status: string }> }>(orgId, "/tasks?filter=mine&page_size=100");
  const projects = useOrgData<Option[]>(orgId, "/projects");
  const rows = rowsOf<TimeEntryRow>(entries.data);
  const taskOptions = useMemo(() => rowsOf<{ id: string; title: string }>(tasks.data).map((t) => ({ id: t.id, name: t.title })), [tasks.data]);
  const drafts = rows.filter((e) => e.ended_at && (e.approval_status === "draft" || e.approval_status === "rejected"));

  const { reload: reloadEntries } = entries;
  const { reload: reloadReport } = report;
  const reload = useCallback(() => {
    reloadEntries();
    reloadReport();
  }, [reloadEntries, reloadReport]);

  useEffect(() => {
    window.addEventListener(TIMER_EVENT, reload);
    return () => window.removeEventListener(TIMER_EVENT, reload);
  }, [reload]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      // Reloads this screen (listener above) and the top-bar timer.
      window.dispatchEvent(new Event(TIMER_EVENT));
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
      return false;
    }
  }

  const categories = (report.data?.by_category ?? []).map((row) => ({ key: row.key, label: tr(categoryLabel(row.key)), seconds: row.seconds }));
  const projectRows = (report.data?.by_project ?? []).map((row) => ({ key: row.id ?? "none", label: row.id ? row.name : tr("No project"), seconds: row.seconds }));

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Time")}
        intro={tr("Use the timer in the top bar, or add time by hand. Submit your week when it's complete.")}
        action={
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link href={`/w/${orgSlug}/time/reports`}>{tr("Reports")}</Link>
            </Button>
            <Button type="button" onClick={() => setAdding(!adding)}>
              {tr("Add time")}
            </Button>
          </div>
        }
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      {adding ? (
        <div className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
          <h2 className="mb-3 font-semibold">{tr("Add time by hand")}</h2>
          <EntryForm
            tasks={taskOptions}
            projects={projects.data ?? []}
            onSubmit={(body: EntryBody) => act(() => api.post(`/orgs/${orgId}/time-entries`, body), tr("Time added."))}
            onCancel={() => setAdding(false)}
          />
        </div>
      ) : null}

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <WeekPicker value={week} onChange={setWeek} />
        <p className="text-sm">
          {tr("Total")}: <span className="font-mono text-lg font-semibold tabular-nums">{formatDuration(report.data?.seconds ?? 0)}</span>
        </p>
      </div>

      <div className="mb-8 grid gap-4 md:grid-cols-2">
        <Breakdown title={tr("By category")} rows={categories} />
        <Breakdown title={tr("By project")} rows={projectRows} />
      </div>

      <Section
        title={tr("Entries")}
        aside={
          drafts.length ? (
            <Button type="button" variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/time-entries/submit`, { week }), tr("Sent to your lead for approval."))}>
              {tr("Submit {n} entries for approval", { n: drafts.length })}
            </Button>
          ) : null
        }
      >
        <ScreenBody state={entries.state} error={entries.error || tr("Could not load time entries")} onRetry={entries.reload}>
          {rows.length === 0 ? (
            <Notice>{tr("No time this week yet.")}</Notice>
          ) : (
            <Rows>
              {rows.map((entry) => (
                <Row key={entry.id}>
                  {editing === entry.id ? (
                    <div className="w-full">
                      <EntryForm
                        entry={entry}
                        tasks={taskOptions}
                        projects={projects.data ?? []}
                        onSubmit={async (body) => {
                          const ok = await act(() => api.patch(`/orgs/${orgId}/time-entries/${entry.id}`, body), tr("Saved."));
                          if (ok) setEditing(null);
                          return ok;
                        }}
                        onCancel={() => setEditing(null)}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{entry.description || entry.task_title || tr("Time entry")}</p>
                        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                          {when(entry.started_at)} · {tr(categoryLabel(entry.category))}
                          {entry.task_title && entry.description ? ` · ${entry.task_title}` : ""}
                          {entry.project_name ? ` · ${entry.project_name}` : ""}
                          {entry.source === "manual" ? ` · ${tr("Added by hand")}` : ""}
                        </p>
                        {entry.approval_status === "rejected" && entry.approval_note ? (
                          <p className="text-sm text-[color:var(--fb-v2-error)]">{tr("Lead's note: {note}", { note: entry.approval_note })}</p>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {entry.ended_at ? <Badge tone={approvalTone(entry.approval_status)}>{tr(approvalLabel(entry.approval_status))}</Badge> : <Badge tone="accent">{tr("Running")}</Badge>}
                        <span className="w-14 text-end font-mono tabular-nums">{formatDuration(entry.seconds)}</span>
                        {entry.can_edit ? (
                          <>
                            <Button type="button" variant="ghost" onClick={() => setEditing(entry.id)}>
                              {tr("Edit")}
                            </Button>
                            <Button type="button" variant="ghost" onClick={() => act(() => api.del(`/orgs/${orgId}/time-entries/${entry.id}`), tr("Entry deleted."))}>
                              {tr("Delete")}
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </>
                  )}
                </Row>
              ))}
            </Rows>
          )}
        </ScreenBody>
      </Section>

      {reviewer ? <ApprovalQueue orgId={orgId} /> : null}
    </div>
  );
}
