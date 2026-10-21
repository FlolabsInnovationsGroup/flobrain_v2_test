"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Badge, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tr = (text: string, vars?: Record<string, string | number>) => string;

const SURFACES: Record<string, string> = {
  room_ai: "Room AI",
  buddy: "Buddies",
  scheduled_agent: "Scheduled agents",
  knowledge_ask: "Ask the org",
  translation: "Translation",
  content_studio: "Content Studio",
  meeting: "Meetings",
  learning: "Learning",
  evaluation: "Evaluations",
  other: "Other",
};
const TOOLS: Record<string, string> = {
  "tasks.create": "Create a task",
  "tasks.assign": "Assign a task",
  "tasks.update_status": "Change a task's status",
  "rooms.post_message": "Post a room message",
  "meetings.create": "Schedule a meeting",
  "email.draft": "Draft an email",
  "content.publish": "Submit a social post",
  "reports.generate": "Generate a team report",
};
const PAUSED: Record<string, string> = {
  creator_inactive: "creator is no longer active",
  buddy_unavailable: "its buddy is no longer available",
  paused_by_user: "paused by a person",
  bad_cron: "its schedule is not valid",
};

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{note}</p> : null}
    </div>
  );
}

const pct = (v: number | null | undefined, tr: Tr) => (v === null || v === undefined ? tr("No data") : `${(v * 100).toFixed(0)}%`);

function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
      <table className="w-full text-sm">
        <thead className="text-[color:var(--fb-v2-text-muted)]">
          <tr>
            {head.map((h) => (
              <th key={h} className="px-4 py-2 text-start font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i} className="border-t border-[color:var(--fb-v2-border)]">
              {cells.map((c, j) => (
                <td key={j} className="px-4 py-2 tabular-nums">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type AgentsData = {
  buddies: { buddy: string; name: string; calls: number; error_rate: number | null; cost: string; proposals: number; executed: number; rejected: number; pending: number; approval_rate: number | null }[];
  schedules: { id: string; name: string; buddy: string; owner: string; is_active: boolean; paused_reason: string; runs: number; done: number; failed: number; skipped: number; proposals: number; cost: string; cost_per_run: string | null; last_run_at: string | null }[];
};

export function PulseAgents() {
  const { orgId } = useAccess();
  const tr = useTr();
  const q = useOrgData<AgentsData>(orgId, "/pulse/agents");
  const d = q.data;
  return (
    <ScreenBody state={q.state} error={q.error} onRetry={q.reload}>
      {d ? (
        <>
          <Section title={tr("Buddies, last 7 days")}>
            {d.buddies.length ? (
              <Table
                head={[tr("Buddy"), tr("Calls"), tr("Error rate"), tr("Cost"), tr("Proposed"), tr("Approved"), tr("Rejected"), tr("Waiting")]}
                rows={d.buddies.map((b) => [b.name || tr("Removed buddy"), b.calls, pct(b.error_rate, tr), `$${b.cost}`, b.proposals, b.executed, b.rejected, b.pending])}
              />
            ) : (
              <Notice>{tr("No buddy use in the last 7 days.")}</Notice>
            )}
          </Section>
          <Section title={tr("Scheduled agents")}>
            {d.schedules.length ? (
              <Table
                head={[tr("Agent"), tr("Owner"), tr("Runs"), tr("Done"), tr("Failed"), tr("Skipped"), tr("Proposed"), tr("Cost per run"), tr("State")]}
                rows={d.schedules.map((s) => [
                  <span key="n">
                    {s.name} <span className="text-[color:var(--fb-v2-text-muted)]">{s.buddy}</span>
                  </span>,
                  s.owner,
                  s.runs,
                  s.done,
                  s.failed,
                  s.skipped,
                  s.proposals,
                  s.cost_per_run ? `$${s.cost_per_run}` : tr("No data"),
                  s.is_active ? (
                    <Badge key="s" tone="good">
                      {tr("Active")}
                    </Badge>
                  ) : (
                    <Badge key="s" tone="waiting">
                      {s.paused_reason && PAUSED[s.paused_reason] ? tr("Paused: {reason}", { reason: tr(PAUSED[s.paused_reason]) }) : tr("Paused")}
                    </Badge>
                  ),
                ])}
              />
            ) : (
              <Notice>{tr("No scheduled agents yet.")}</Notice>
            )}
          </Section>
        </>
      ) : null}
    </ScreenBody>
  );
}

type Group = { label: string; cost: string; calls: number; tokens: number };
type CostData = {
  days: number;
  platform_cost: string;
  platform_calls: number;
  cost_per_call: string | null;
  unpriced_calls: number;
  own_key_calls: number;
  own_key_tokens: number;
  gpu_seconds: number;
  gpu_cost: string;
  gpu_unpriced_renders: number;
  series: { day: string; cost: string; own_key_tokens: number; platform_tokens: number }[];
  by_model: Group[];
  by_team: Group[];
  by_member: Group[];
  by_surface: Group[];
  budgets?: { id: string; scope_type: string; scope_name: string; limit: string; spent: string; currency: string; state: string; on_exceed: string }[];
};

export function PulseCost() {
  const { orgId } = useAccess();
  const tr = useTr();
  const q = useOrgData<CostData>(orgId, "/pulse/cost");
  const d = q.data;
  const groups = (items: Group[], label: (g: Group) => string) =>
    items.length ? (
      <Rows>
        {items.map((g) => (
          <Row key={g.label}>
            <span>{label(g)}</span>
            <span className="tabular-nums">
              ${g.cost} <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} calls", { n: g.calls })}</span>
            </span>
          </Row>
        ))}
      </Rows>
    ) : (
      <Notice>{tr("No platform spend.")}</Notice>
    );
  return (
    <ScreenBody state={q.state} error={q.error} onRetry={q.reload}>
      {d ? (
        <>
          <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label={tr("Platform cost, last {n} days", { n: d.days })} value={`$${d.platform_cost}`} note={d.unpriced_calls ? tr("{n} calls have no price yet", { n: d.unpriced_calls }) : tr("At cost, no markup")} />
            <Tile label={tr("Cost per call")} value={d.cost_per_call ? `$${d.cost_per_call}` : tr("No data")} note={tr("{n} platform calls", { n: d.platform_calls })} />
            <Tile label={tr("Own keys")} value={d.own_key_tokens.toLocaleString()} note={tr("tokens in {n} calls, billed by the provider", { n: d.own_key_calls })} />
            <Tile label={tr("GPU renders")} value={`$${d.gpu_cost}`} note={d.gpu_unpriced_renders ? tr("{s} s, {n} renders without a price", { s: d.gpu_seconds, n: d.gpu_unpriced_renders }) : tr("{s} GPU seconds", { s: d.gpu_seconds })} />
          </div>
          <Section title={tr("Platform cost per day")}>
            {d.series.length ? (
              <figure className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={d.series.map((s) => ({ ...s, value: Number(s.cost) }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid vertical={false} stroke="var(--fb-v2-border)" />
                      <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
                      <YAxis tickLine={false} axisLine={false} width={48} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
                      <Tooltip
                        cursor={{ fill: "var(--fb-v2-border)" }}
                        contentStyle={{ background: "var(--fb-v2-page)", border: "1px solid var(--fb-v2-border)", borderRadius: 8, color: "var(--fb-v2-text)" }}
                        formatter={(value) => [`$${Number(value ?? 0).toFixed(4)}`, ""]}
                      />
                      <Bar dataKey="value" fill="#7c6bff" radius={[4, 4, 0, 0]} maxBarSize={28} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <figcaption className="sr-only">{d.series.map((s) => tr("{day}: ${cost}", { day: s.day, cost: s.cost })).join(tr("; "))}</figcaption>
              </figure>
            ) : (
              <Notice>{tr("No AI calls in this period.")}</Notice>
            )}
          </Section>
          {d.budgets?.length ? (
            <Section title={tr("Budgets this month")}>
              <Rows>
                {d.budgets.map((b) => (
                  <Row key={b.id}>
                    <span>{b.scope_name}</span>
                    <span className="flex items-center gap-2 tabular-nums">
                      {tr("{spent} of {limit} {currency}", { spent: Number(b.spent).toFixed(2), limit: Number(b.limit).toFixed(2), currency: b.currency })}
                      <Badge tone={b.state === "exceeded" ? "bad" : b.state === "alert" ? "waiting" : "good"}>
                        {b.state === "exceeded" ? tr("Used up") : b.state === "alert" ? tr("Near the limit") : tr("On track")}
                      </Badge>
                    </span>
                  </Row>
                ))}
              </Rows>
            </Section>
          ) : null}
          <div className="grid gap-6 md:grid-cols-2">
            <Section title={tr("By model")}>{groups(d.by_model, (g) => g.label)}</Section>
            <Section title={tr("By feature")}>{groups(d.by_surface, (g) => (SURFACES[g.label] ? tr(SURFACES[g.label]) : g.label))}</Section>
            <Section title={tr("By team")}>{groups(d.by_team, (g) => (g.label === "No team" ? tr("No team") : g.label))}</Section>
            <Section title={tr("Top members")}>{groups(d.by_member, (g) => (g.label === "Unknown" ? tr("Unknown") : g.label === "People who keep their insights personal" ? tr(g.label) : g.label))}</Section>
          </div>
        </>
      ) : null}
    </ScreenBody>
  );
}

type GovernanceData = {
  days: number;
  proposals: number;
  by_status: Record<string, number>;
  by_tool: ({ tool: string; total: number } & Record<string, number | string>)[];
  approval_rate: number | null;
  edited_before_approval: number;
  median_decision_seconds: number | null;
  denied_at_approval: number;
  blocked_traces: number;
  pending_buddy_shares: number;
  paused_agents: { name: string; reason: string }[];
  inference_scope: string;
};

function duration(seconds: number | null, tr: Tr) {
  if (seconds === null) return tr("No data");
  if (seconds < 90) return tr("{n} s", { n: Math.round(seconds) });
  if (seconds < 5400) return tr("{n} min", { n: Math.round(seconds / 60) });
  return tr("{n} h", { n: Math.round(seconds / 3600) });
}

export function PulseGovernance() {
  const { orgId } = useAccess();
  const tr = useTr();
  const q = useOrgData<GovernanceData>(orgId, "/pulse/governance");
  const d = q.data;
  const n = (k: string) => Number(d?.by_status[k] ?? 0);
  return (
    <ScreenBody state={q.state} error={q.error} onRetry={q.reload}>
      {d ? (
        <>
          <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("AI never acts on its own: every action below waited for a person. Counts only; what was proposed stays with the person it was proposed to.")}
          </p>
          <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label={tr("Proposed, last {n} days", { n: d.days })} value={String(d.proposals)} note={tr("{n} waiting now", { n: n("proposed") })} />
            <Tile label={tr("Approval rate")} value={pct(d.approval_rate, tr)} note={tr("{a} done, {r} rejected, {e} expired", { a: n("executed"), r: n("rejected"), e: n("expired") })} />
            <Tile label={tr("Edited before approval")} value={String(d.edited_before_approval)} note={tr("Median time to decide: {t}", { t: duration(d.median_decision_seconds, tr) })} />
            <Tile label={tr("Stopped at approval")} value={String(d.denied_at_approval)} note={tr("Permission changed or the tool was off")} />
          </div>
          <Section title={tr("By action")}>
            {d.by_tool.length ? (
              <Table
                head={[tr("Action"), tr("Proposed"), tr("Done"), tr("Rejected"), tr("Expired"), tr("Waiting")]}
                rows={d.by_tool.map((t) => [TOOLS[t.tool] ? tr(TOOLS[t.tool]) : t.tool, t.total, Number(t.executed ?? 0), Number(t.rejected ?? 0), Number(t.expired ?? 0), Number(t.proposed ?? 0)])}
              />
            ) : (
              <Notice>{tr("No AI actions proposed.")}</Notice>
            )}
          </Section>
          <div className="grid gap-6 md:grid-cols-2">
            <Section title={tr("Policy")}>
              <Rows>
                <Row>
                  <span>{tr("Where AI may run")}</span>
                  <span>{d.inference_scope === "private_only" ? tr("Self-hosted models only") : tr("Platform and external providers")}</span>
                </Row>
                <Row>
                  <span>{tr("Blocked requests")}</span>
                  <span className="tabular-nums">{d.blocked_traces}</span>
                </Row>
                <Row>
                  <span>{tr("Buddy shares waiting")}</span>
                  <span className="tabular-nums">{d.pending_buddy_shares}</span>
                </Row>
              </Rows>
            </Section>
            <Section title={tr("Paused agents")}>
              <Rows>
                {d.paused_agents.length === 0 ? <Row>{tr("None.")}</Row> : null}
                {d.paused_agents.map((a, i) => (
                  <Row key={i}>
                    <span>{a.name}</span>
                    <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{PAUSED[a.reason] ? tr(PAUSED[a.reason]) : a.reason || tr("Paused")}</span>
                  </Row>
                ))}
              </Rows>
            </Section>
          </div>
        </>
      ) : null}
    </ScreenBody>
  );
}

type IncidentRow = {
  id: string;
  title: string;
  severity: string;
  status: string;
  platform: boolean;
  started_at: string;
  resolved_at: string | null;
  ai_calls: number;
  ai_errors: number;
  ai_error_rate: number | null;
};
const SEVERITY: Record<string, string> = { minor: "Minor", major: "Major", critical: "Critical" };
const INCIDENT_STATUS: Record<string, string> = { investigating: "Investigating", identified: "Identified", monitoring: "Monitoring", resolved: "Resolved" };

export function PulseIncidents() {
  const { orgId } = useAccess();
  const tr = useTr();
  const q = useOrgData<IncidentRow[]>(orgId, "/pulse/incidents", { list: true });
  return (
    <ScreenBody state={q.state} error={q.error} emptyLabel={tr("No incidents in the last 90 days.")} onRetry={q.reload}>
      <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Each incident with how AI calls did while it was open.")}</p>
      <Rows>
        {(q.data ?? []).map((i) => (
          <Row key={i.id}>
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                {i.title} {i.platform ? <span className="text-sm font-normal text-[color:var(--fb-v2-text-muted)]">{tr("(FloBrain platform)")}</span> : null}
              </p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {i.resolved_at ? tr("{start} to {end}", { start: when(i.started_at), end: when(i.resolved_at) }) : tr("Since {start}", { start: when(i.started_at) })}.{" "}
                {i.ai_calls ? tr("{n} AI calls, {e} failed ({rate}).", { n: i.ai_calls, e: i.ai_errors, rate: pct(i.ai_error_rate, tr) }) : tr("No AI calls in that time.")}
              </p>
            </div>
            <div className="flex gap-2">
              <Badge tone={i.severity === "critical" ? "bad" : i.severity === "major" ? "waiting" : "neutral"}>{tr(SEVERITY[i.severity] ?? i.severity)}</Badge>
              <Badge tone={i.status === "resolved" ? "good" : "waiting"}>{tr(INCIDENT_STATUS[i.status] ?? i.status)}</Badge>
            </div>
          </Row>
        ))}
      </Rows>
    </ScreenBody>
  );
}
