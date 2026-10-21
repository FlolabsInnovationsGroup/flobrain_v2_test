"use client";

import Link from "next/link";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Badge, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import {
  drilldownTasks,
  formatBlockedDuration,
  isMissionControlEmpty,
  metricCards,
  peopleLine,
  workloadDrilldown,
  type WorkloadRow,
} from "@/lib/v2/screens/missionControl";
import { priorityLabel, priorityTone } from "@/lib/v2/screens/tasks";
import { formatDuration } from "@/lib/v2/screens/time";
import { useOrgData } from "@/lib/v2/useOrgData";

type People = Array<{ id: string; name: string }>;
type Payload = {
  assigned_open: number;
  assigned_done: number;
  blocked: number;
  overdue: number;
  total?: number;
  done?: number;
  accomplishments: Array<{ id: string; title: string; done_at: string; assignees: string[]; people?: People }>;
  blockers: Array<{ id: string; title: string; reason?: string; blocked_seconds: number; assignees: string[]; people?: People }>;
  deadlines: Array<{ id: string; title: string; due_on: string; priority: string; urgency?: string; is_blocked?: boolean; assignees: string[]; people?: People }>;
  workload: WorkloadRow[];
};

const STATUS: Record<string, string> = { to_do: "To Do", in_progress: "In Progress", done: "Done" };

export function MissionControlScreen({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const admin = access?.org_role === "owner" || access?.org_role === "admin" || !!access?.is_platform_admin;
  const teams = useOrgData<Array<{ id: string; name: string }>>(orgId, "/teams");
  const choices = (teams.data ?? []).filter((t) => admin || access?.leads_teams.includes(t.id));
  const [team, setTeam] = useState("");
  const data = useOrgData<Payload>(orgId, `/mission-control${team ? `?team=${team}` : ""}`);
  const [drill, setDrill] = useState<string | null>(null);
  const payload = data.data;
  const selected = payload ? workloadDrilldown(payload.workload, drill) : null;
  const task = (id: string) => `/w/${orgSlug}/tasks?task=${id}`;

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Mission Control")}
        intro={tr("What your teams finished, what is stuck, what is due next, and who has room for more.")}
        action={
          choices.length ? (
            <select className="v2-input w-auto" aria-label={tr("Team")} value={team} onChange={(e) => setTeam(e.target.value)}>
              <option value="">{admin ? tr("All teams") : tr("All my teams")}</option>
              {choices.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          ) : null
        }
      />
      <ScreenBody state={data.state} error={data.error || tr("Could not load Mission Control")} onRetry={data.reload}>
        {payload ? (
          <div>
            {isMissionControlEmpty(payload) ? <Notice>{tr("No team activity yet")}</Notice> : null}
            <div className="mb-8 grid gap-3 sm:grid-cols-5">
              {[
                ...metricCards(payload).map((card) => ({ id: card.id, label: tr(card.id === "open" ? "state|Open" : card.label), value: String(card.value) })),
                { id: "total", label: tr("Tasks done vs total"), value: `${payload.done ?? 0} / ${payload.total ?? 0}` },
              ].map((card) => (
                <div key={card.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{card.label}</p>
                  <p className="mt-1 text-2xl font-semibold">{card.value}</p>
                </div>
              ))}
            </div>

            <div className="grid gap-x-6 lg:grid-cols-2">
              <Section title={tr("Current blockers")}>
                {payload.blockers.length === 0 ? <Notice>{tr("Nothing is blocked.")}</Notice> : null}
                <Rows>
                  {payload.blockers.map((item) => (
                    <Row key={item.id}>
                      <div className="min-w-0 flex-1">
                        <Link className="font-medium hover:underline" href={task(item.id)}>
                          {item.title}
                        </Link>
                        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                          {item.reason || tr("No reason given")} · {peopleLine(item.people) || tr("Nobody assigned")}
                        </p>
                      </div>
                      <Badge tone="bad">{tr("Blocked for {time}", { time: formatBlockedDuration(item.blocked_seconds) })}</Badge>
                    </Row>
                  ))}
                </Rows>
              </Section>

              <Section title={tr("Upcoming deadlines")}>
                {payload.deadlines.length === 0 ? <Notice>{tr("No open tasks with a due date.")}</Notice> : null}
                <Rows>
                  {payload.deadlines.map((item) => (
                    <Row key={item.id}>
                      <div className="min-w-0 flex-1">
                        <Link className="font-medium hover:underline" href={task(item.id)}>
                          {item.title}
                        </Link>
                        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                          {item.due_on} · {peopleLine(item.people) || tr("Nobody assigned")}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {item.urgency === "overdue" ? <Badge tone="bad">{tr("Overdue")}</Badge> : null}
                        <Badge tone={priorityTone(item.priority)}>{tr(priorityLabel(item.priority))}</Badge>
                      </div>
                    </Row>
                  ))}
                </Rows>
              </Section>
            </div>

            <Section title={tr("Top accomplishments this week")}>
              {payload.accomplishments.length === 0 ? <Notice>{tr("Nothing finished in the last 7 days.")}</Notice> : null}
              <Rows>
                {payload.accomplishments.map((item) => (
                  <Row key={item.id}>
                    <span className="font-medium">{item.title}</span>
                    <span className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {peopleLine(item.people) || tr("Nobody assigned")} · {new Date(item.done_at).toLocaleDateString()}
                    </span>
                  </Row>
                ))}
              </Rows>
            </Section>

            <Section title={tr("Workload")}>
              <Rows>
                {payload.workload.map((row) => (
                  <Row key={row.user_id}>
                    <button
                      type="button"
                      aria-expanded={drill === row.user_id}
                      className="text-start font-medium text-[color:var(--fb-v2-accent)] hover:underline"
                      onClick={() => setDrill(drill === row.user_id ? null : row.user_id)}
                    >
                      {row.name || row.user_id.slice(0, 8)}
                    </button>
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <span>{tr("{n} open", { n: row.open_tasks })}</span>
                      {row.blocked_tasks ? <Badge tone="bad">{tr("{n} blocked", { n: row.blocked_tasks })}</Badge> : null}
                      <span className="font-mono tabular-nums">
                        {row.weekly_target_hours
                          ? tr("{done} of {target} h", { done: formatDuration(row.seconds_7d), target: row.weekly_target_hours.replace(/\.00$/, "") })
                          : formatDuration(row.seconds_7d)}
                      </span>
                      {row.capacity_seconds != null ? (
                        <Badge tone={row.capacity_seconds > 0 ? "good" : "waiting"}>
                          {row.capacity_seconds > 0 ? tr("{time} free", { time: formatDuration(row.capacity_seconds) }) : tr("At capacity")}
                        </Badge>
                      ) : null}
                    </div>
                    {selected && selected.user_id === row.user_id ? (
                      <ul className="w-full space-y-1 border-t border-[color:var(--fb-v2-border)] pt-2 text-sm">
                        {drilldownTasks(selected).length === 0 ? <li className="text-[color:var(--fb-v2-text-muted)]">{tr("No tasks assigned.")}</li> : null}
                        {drilldownTasks(selected).map((t) => (
                          <li key={t.id} className="flex flex-wrap items-center justify-between gap-2">
                            <Link className="hover:underline" href={task(t.id)}>
                              {t.title}
                            </Link>
                            <span className="flex items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
                              {t.is_blocked ? <Badge tone="bad">{tr("Blocked")}</Badge> : null}
                              {STATUS[t.status] ? tr(STATUS[t.status]) : null}
                              {t.due_on ? ` · ${t.due_on}` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </Row>
                ))}
              </Rows>
            </Section>
          </div>
        ) : null}
      </ScreenBody>
    </div>
  );
}
