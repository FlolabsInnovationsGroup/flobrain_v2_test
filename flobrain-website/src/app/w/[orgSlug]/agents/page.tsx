"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Schedule = {
  id: string;
  name: string;
  buddy: string;
  trigger_type: "cron" | "event";
  cron: string | null;
  event: string | null;
  instructions: string;
  is_active: boolean;
  paused_reason: string;
  last_run_at: string | null;
  next_run_at: string | null;
};
type Run = {
  id: string;
  status: string;
  reason: string;
  error: string;
  proposals: number;
  started_at: string | null;
  finished_at: string | null;
  output?: string;
  proposal_items?: { id: string; summary: string; status: string }[];
};

const PRESETS = [
  ["0 9 * * 1", "Mondays at 09:00"],
  ["0 9 * * 1-5", "Weekdays at 09:00"],
  ["0 17 * * 5", "Fridays at 17:00"],
] as const;
const EVENTS = [
  ["task.overdue", "When a task becomes overdue"],
  ["member.joined", "When someone joins the org"],
  ["meeting.ended", "When a meeting ends"],
] as const;

/** Run states from the API (``AgentRun.status``) as words and badge tones. */
const RUN_STATUS: Record<string, [string, "neutral" | "waiting" | "good" | "bad"]> = {
  queued: ["Queued", "waiting"],
  running: ["Running", "waiting"],
  done: ["Done", "good"],
  failed: ["Failed", "bad"],
  skipped: ["Skipped", "neutral"],
};
const RUN_ERRORS: Record<string, string> = {
  creator_inactive: "The person who made it is no longer active.",
  buddy_unavailable: "Its buddy is no longer available to its creator.",
  flag_off: "Scheduled agents are switched off.",
  paused: "The agent was paused.",
  no_worker: "No background worker is running.",
  budget_exceeded: "The AI budget is used up.",
};
const PROPOSAL_STATUS: Record<string, string> = {
  proposed: "Waiting for approval",
  executed: "Done",
  rejected: "Rejected",
  failed: "Failed",
  expired: "Expired",
};

function triggerText(s: Schedule, tr: (text: string, vars?: Record<string, string | number>) => string) {
  if (s.trigger_type === "event") {
    const label = EVENTS.find(([k]) => k === s.event)?.[1];
    return label ? tr(label) : (s.event ?? "");
  }
  const label = PRESETS.find(([k]) => k === s.cron)?.[1];
  return label ? tr(label) : tr("Schedule {cron}", { cron: s.cron ?? "" });
}

export default function AgentsPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<Schedule[]>(orgId, "/agents/schedules", { list: true });
  const { data: buddies } = useOrgData<{ id: string; name: string }[]>(orgId, "/buddies");
  const [form, setForm] = useState<{ name: string; buddy: string; trigger: string; cron: string; event: string; instructions: string }>({
    name: "",
    buddy: "",
    trigger: "cron",
    cron: PRESETS[0][0],
    event: EVENTS[0][0],
    instructions: "",
  });
  const [adding, setAdding] = useState(false);
  const [runs, setRuns] = useState<Record<string, Run[]>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const buddyName = (id: string) => rowsOf<{ id: string; name: string }>(buddies).find((b) => b.id === id)?.name ?? tr("a buddy");

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

  async function create(event: React.FormEvent) {
    event.preventDefault();
    await act(
      () =>
        api.post(`/orgs/${orgId}/agents/schedules`, {
          name: form.name,
          buddy: form.buddy || rowsOf<{ id: string }>(buddies)[0]?.id,
          trigger_type: form.trigger,
          cron: form.trigger === "cron" ? form.cron : undefined,
          event: form.trigger === "event" ? form.event : undefined,
          instructions: form.instructions,
        }),
      tr("Agent saved. It proposes actions; you approve them."),
    );
    setAdding(false);
  }

  async function showRuns(id: string) {
    const rows = rowsOf<Run>(await api.get(`/orgs/${orgId}/agents/schedules/${id}/runs`));
    setRuns((prev) => ({ ...prev, [id]: rows }));
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Agents")}
        intro={tr("A buddy that works on a schedule or when something happens. It can read and propose, never act without approval.")}
        action={<Button onClick={() => setAdding((v) => !v)}>{adding ? tr("Close") : tr("New agent")}</Button>}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {adding ? (
        <form onSubmit={create} className="mb-8 rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
          <Field label={tr("Name")}>
            <input className="v2-input" maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={tr("Buddy")}>
            <select className="v2-input" value={form.buddy} onChange={(e) => setForm({ ...form, buddy: e.target.value })}>
              {rowsOf<{ id: string; name: string }>(buddies).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={tr("When it runs")}>
            <select className="v2-input" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })}>
              <option value="cron">{tr("On a schedule")}</option>
              <option value="event">{tr("When something happens")}</option>
            </select>
          </Field>
          {form.trigger === "cron" ? (
            <Field label={tr("Schedule")}>
              <select className="v2-input" value={form.cron} onChange={(e) => setForm({ ...form, cron: e.target.value })}>
                {PRESETS.map(([k, label]) => (
                  <option key={k} value={k}>
                    {tr(label)}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label={tr("Event")}>
              <select className="v2-input" value={form.event} onChange={(e) => setForm({ ...form, event: e.target.value })}>
                {EVENTS.map(([k, label]) => (
                  <option key={k} value={k}>
                    {tr(label)}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={tr("What to do")}>
            <textarea
              className="v2-input min-h-24"
              required
              value={form.instructions}
              onChange={(e) => setForm({ ...form, instructions: e.target.value })}
            />
          </Field>
          <Button type="submit">{tr("Save agent")}</Button>
        </form>
      ) : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("No agents yet. Create one to draft reports or follow up on overdue tasks.")} onRetry={reload}>
        <Rows>
          {rowsOf<Schedule>(data).map((s) => (
            <Row key={s.id} className="items-start">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{s.name || tr("Untitled agent")}</p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("{trigger}, using {buddy}.", { trigger: triggerText(s, tr), buddy: buddyName(s.buddy) })}
                  {s.next_run_at ? ` ${tr("Next run {when}.", { when: when(s.next_run_at) })}` : ""}
                </p>
                <p className="mt-1 text-sm">{s.instructions}</p>
                {runs[s.id] ? (
                  <ul className="mt-3 space-y-3 text-sm">
                    {runs[s.id].length === 0 ? <li className="text-[color:var(--fb-v2-text-muted)]">{tr("No runs yet.")}</li> : null}
                    {runs[s.id].map((r) => {
                      const [label, tone] = RUN_STATUS[r.status] ?? [r.status, "neutral" as const];
                      return (
                        <li key={r.id} className="rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                          <p>
                            <Badge tone={tone}>{tr(label)}</Badge> <span className="text-[color:var(--fb-v2-text-muted)]">{when(r.started_at || r.finished_at)}</span>
                            {r.error ? <span className="text-[color:var(--fb-v2-error)]"> {RUN_ERRORS[r.error] ? tr(RUN_ERRORS[r.error]) : r.error}</span> : null}
                          </p>
                          {r.output ? <p className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap">{r.output}</p> : null}
                          {r.proposal_items?.length ? (
                            <ul className="mt-2 space-y-1">
                              {r.proposal_items.map((p) => (
                                <li key={p.id} className="flex flex-wrap items-center gap-2">
                                  <span>{p.summary}</span>
                                  <Badge tone={p.status === "proposed" ? "waiting" : p.status === "executed" ? "good" : "neutral"}>{tr(PROPOSAL_STATUS[p.status] ?? p.status)}</Badge>
                                  {p.status === "proposed" ? (
                                    <Link href={`/w/${orgSlug}/approvals`} className="font-medium underline">
                                      {tr("Review in Approvals")}
                                    </Link>
                                  ) : null}
                                </li>
                              ))}
                            </ul>
                          ) : r.output === undefined && r.proposals ? (
                            <p className="mt-1 text-[color:var(--fb-v2-text-muted)]">{tr("{n} action(s) proposed to its creator.", { n: r.proposals })}</p>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {!s.is_active ? <Badge>{s.paused_reason ? tr("Paused: {reason}", { reason: s.paused_reason }) : tr("Paused")}</Badge> : null}
                <Button
                  variant="outline"
                  onClick={() =>
                    act(async () => {
                      const run = await api.post<Run>(`/orgs/${orgId}/agents/schedules/${s.id}/run`);
                      await showRuns(s.id);
                      return run;
                    }, tr("Started. Its draft is in History, and anything it proposes waits in Approvals."))
                  }
                >
                  {tr("Run now")}
                </Button>
                <Button variant="ghost" onClick={() => showRuns(s.id)}>
                  {tr("History")}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() =>
                    act(() => api.patch(`/orgs/${orgId}/agents/schedules/${s.id}`, { is_active: !s.is_active }), s.is_active ? tr("Paused.") : tr("Resumed."))
                  }
                >
                  {s.is_active ? tr("Pause") : tr("Resume")}
                </Button>
              </div>
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </div>
  );
}
