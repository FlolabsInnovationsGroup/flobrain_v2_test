"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PulseAgents, PulseCost, PulseGovernance, PulseIncidents } from "@/components/v2/ai/PulseViews";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

type Overview = {
  scope: "org" | "teams";
  calls: number;
  errors: number;
  error_rate: number | null;
  tokens: number;
  cost: string;
  unpriced_calls: number;
  byok_calls: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  series: { day: string; calls: number; errors: number }[];
  governance: Record<string, number>;
  evals: { suite: string; model: string; pass_rate: number | null; threshold: number }[];
};
type ModelRow = { provider: string; model: string; calls: number; error_rate: number; tokens: number; cost: string; latency_p95_ms: number | null };
type Trace = { id: string; surface: string; model: string; outcome: string; latency_ms: number | null; user: string | null; created_at: string; context_sources?: unknown[]; tool_calls?: unknown[]; permission_decisions?: unknown[] };
type Suite = { id: string; name: string; threshold: number; cases: { id: string; name: string }[]; last_run: { id: string; status: string; pass_rate: number | null; model: string } | null };
type Run = { id: string; status: string; pass_rate: number | null; threshold: number; results: { case: string; passed: boolean; checks: { check: string; passed: boolean }[]; latency_ms: number | null; error: string }[] };
type Policy = { primary_model: string; fallback_models: string[]; latency_threshold_ms: number | null; max_task_cost: string | null };
type Alert = { id: string; metric: string; threshold: number; window_minutes: number; last_fired_at: string | null };

const TABS = ["Overview", "Models", "Agents", "Cost", "Governance", "Traces", "Evaluations", "Routing", "Incidents", "Alerts"] as const;
/** Tabs that only owners and admins (``pulse.view``) can open; team leads see Overview. */
const ADMIN_TABS = new Set<string>(["Models", "Agents", "Cost", "Governance", "Traces", "Evaluations", "Routing", "Incidents", "Alerts"]);
const GOVERNANCE: Record<string, string> = {
  proposed: "Proposed",
  approved: "Approved",
  executed: "Done",
  rejected: "Rejected",
  failed: "Failed",
  expired: "Expired",
};
const STATUS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  done: "Done",
  failed: "Failed",
  completed: "Completed",
  fallback: "Completed on a fallback model",
  error: "Error",
};
const SURFACES: Record<string, string> = {
  buddy: "Buddy",
  content_studio: "Content studio",
  evaluation: "Evaluation",
  knowledge_ask: "Ask the org",
  learning: "Learning",
  room_ai: "Room AI",
  scheduled_agent: "Scheduled agent",
  translation: "Translation",
};
const TRACE_PARTS = [
  ["context_sources", "Context sources"],
  ["tool_calls", "Tool calls"],
  ["permission_decisions", "Permission decisions"],
] as const;
const METRICS: Record<string, string> = {
  error_rate: "Error rate",
  p95_latency_ms: "p95 latency (ms)",
  daily_cost: "AI cost",
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

export default function PulsePage() {
  const { orgId, access } = useAccess();
  const admin = !!access?.permissions.includes("pulse.view");
  const tr = useTr();
  const pct = (v: number | null) => (v === null ? tr("No data") : `${(v * 100).toFixed(1)}%`);
  const label = (map: Record<string, string>, key: string) => (map[key] ? tr(map[key]) : key);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const overview = useOrgData<Overview>(orgId, tab === "Overview" ? "/pulse/overview" : null);
  const models = useOrgData<ModelRow[]>(orgId, tab === "Models" ? "/pulse/models" : null, { list: true });
  const traces = useOrgData<Trace[]>(orgId, tab === "Traces" ? "/pulse/traces" : null, { list: true });
  const suites = useOrgData<Suite[]>(orgId, tab === "Evaluations" ? "/pulse/suites" : null, { list: true });
  const policy = useOrgData<Policy>(orgId, tab === "Routing" ? "/pulse/routing" : null);
  const alerts = useOrgData<Alert[]>(orgId, tab === "Alerts" ? "/pulse/alerts" : null, { list: true });
  const [trace, setTrace] = useState<Trace | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [preview, setPreview] = useState<{ model: string | null; steps?: { model: string; chosen?: boolean; skipped?: string }[]; reason?: string; note?: string } | null>(null);
  const [form, setForm] = useState({ primary: "", fallbacks: "", latency: "", suite: "", prompt: "", contains: "", metric: "error_rate", threshold: "0.1" });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const o = overview.data;

  async function act<T>(fn: () => Promise<T>, ok: string, after?: (v: T) => void) {
    setMessage(null);
    try {
      const v = await fn();
      setMessage({ kind: "ok", text: ok });
      after?.(v);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Pulse")}
        intro={`${tr("How AI is doing in {org}: quality, cost and speed, from real usage records.", { org: access?.org.name ?? tr("your organization") })}${access?.org.demo ? ` ${tr("This is demo data.")}` : ""}`}
      />
      <div role="tablist" className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--fb-v2-border)]">
        {TABS.filter((name) => admin || !ADMIN_TABS.has(name)).map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm", tab === name ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]")}
          >
            {tr(name)}
          </button>
        ))}
      </div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      {tab === "Overview" ? (
        <ScreenBody state={overview.state} error={overview.error} onRetry={overview.reload}>
          {o ? (
            <>
              {o.scope === "teams" ? <Notice>{tr("Showing the teams you lead.")}</Notice> : null}
              <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Tile label={tr("AI calls, last 7 days")} value={o.calls.toLocaleString()} note={tr("{n} on members' own keys", { n: o.byok_calls })} />
                <Tile label={tr("Error rate")} value={pct(o.error_rate)} note={tr("{n} failed calls", { n: o.errors })} />
                <Tile label={tr("Latency p50 / p95")} value={o.latency_p50_ms === null ? tr("No data") : tr("{p50} / {p95} ms", { p50: o.latency_p50_ms, p95: o.latency_p95_ms ?? "" })} />
                <Tile label={tr("Platform cost")} value={`$${o.cost}`} note={o.unpriced_calls ? tr("{n} calls have no price yet", { n: o.unpriced_calls }) : tr("From the price table")} />
              </div>
              <Section title={tr("Calls per day")}>
                {o.series.length ? (
                  <figure className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                    <div className="h-56">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={o.series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                          <CartesianGrid vertical={false} stroke="var(--fb-v2-border)" />
                          <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
                          <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={36} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
                          <Tooltip
                            cursor={{ fill: "var(--fb-v2-border)" }}
                            contentStyle={{ background: "var(--fb-v2-page)", border: "1px solid var(--fb-v2-border)", borderRadius: 8, color: "var(--fb-v2-text)" }}
                            formatter={(value, _n, item) => [tr("{calls} calls, {failed} failed", { calls: Number(value ?? 0), failed: (item?.payload as { errors?: number } | undefined)?.errors ?? 0 }), ""]}
                          />
                          <Bar dataKey="calls" fill="#7c6bff" radius={[4, 4, 0, 0]} maxBarSize={28} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <figcaption className="sr-only">
                      {o.series.map((s) => tr("{day}: {calls} calls, {failed} failed", { day: s.day, calls: s.calls, failed: s.errors })).join(tr("; "))}
                    </figcaption>
                  </figure>
                ) : (
                  <Notice>{tr("No AI calls in the last 7 days.")}</Notice>
                )}
              </Section>
              <div className="grid gap-6 md:grid-cols-2">
                <Section title={tr("Governance")}>
                  <Rows>
                    {Object.keys(o.governance).length === 0 ? <Row>{tr("No AI actions proposed.")}</Row> : null}
                    {Object.entries(o.governance).map(([status, n]) => (
                      <Row key={status}>
                        <span className="capitalize">{label(GOVERNANCE, status)}</span>
                        <span className="tabular-nums">{n}</span>
                      </Row>
                    ))}
                  </Rows>
                </Section>
                <Section title={tr("Latest evaluations")}>
                  <Rows>
                    {o.evals.length === 0 ? <Row>{tr("No evaluation runs yet.")}</Row> : null}
                    {o.evals.map((e, i) => (
                      <Row key={i}>
                        <span>
                          {e.suite} <span className="text-[color:var(--fb-v2-text-muted)]">{e.model || tr("default model")}</span>
                        </span>
                        <Badge tone={(e.pass_rate ?? 0) >= e.threshold ? "good" : "bad"}>{e.pass_rate ?? 0}%</Badge>
                      </Row>
                    ))}
                  </Rows>
                </Section>
              </div>
            </>
          ) : null}
        </ScreenBody>
      ) : null}

      {tab === "Models" ? (
        <ScreenBody state={models.state} error={models.error} emptyLabel={tr("No model calls in the last 7 days.")} onRetry={models.reload}>
          <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
            <table className="w-full text-sm">
              <thead className="text-start text-[color:var(--fb-v2-text-muted)]">
                <tr>
                  {["Model", "Calls", "Error rate", "p95 latency", "Tokens", "Cost"].map((h) => (
                    <th key={h} className="px-4 py-2 text-start font-medium">
                      {tr(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rowsOf<ModelRow>(models.data).map((m) => (
                  <tr key={`${m.provider}/${m.model}`} className="border-t border-[color:var(--fb-v2-border)]">
                    <td className="px-4 py-2">
                      {m.model || tr("unknown")} <span className="text-[color:var(--fb-v2-text-muted)]">{m.provider}</span>
                    </td>
                    <td className="px-4 py-2 tabular-nums">{m.calls}</td>
                    <td className="px-4 py-2 tabular-nums">{pct(m.error_rate)}</td>
                    <td className="px-4 py-2 tabular-nums">{m.latency_p95_ms ?? tr("No data")}</td>
                    <td className="px-4 py-2 tabular-nums">{m.tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 tabular-nums">${m.cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ScreenBody>
      ) : null}

      {tab === "Agents" ? <PulseAgents /> : null}
      {tab === "Cost" ? <PulseCost /> : null}
      {tab === "Governance" ? <PulseGovernance /> : null}
      {tab === "Incidents" ? <PulseIncidents /> : null}

      {tab === "Traces" ? (
        <ScreenBody state={traces.state} error={traces.error} emptyLabel={tr("No traces yet.")} onRetry={traces.reload}>
          <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
            <Rows>
              {rowsOf<Trace>(traces.data).map((t) => (
                <Row key={t.id}>
                  <button type="button" className="min-w-0 flex-1 text-start" onClick={() => api.get<Trace>(`/orgs/${orgId}/pulse/traces/${t.id}`).then(setTrace)}>
                    <span className="font-medium">{SURFACES[t.surface] ? tr(SURFACES[t.surface]) : t.surface.replace("_", " ")}</span> <span className="text-[color:var(--fb-v2-text-muted)]">{t.model}</span>
                    <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">
                      {when(t.created_at)}
                      {t.user ? ` ${tr("by {user}", { user: t.user })}` : ""}
                      {t.latency_ms !== null ? tr(", {ms} ms", { ms: t.latency_ms }) : ""}
                    </span>
                  </button>
                  <Badge tone={t.outcome === "completed" ? "good" : t.outcome === "fallback" ? "waiting" : "bad"}>{label(STATUS, t.outcome)}</Badge>
                </Row>
              ))}
            </Rows>
            <aside className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm">
              {trace ? (
                <>
                  <p className="font-semibold">{tr("Trace {id}", { id: trace.id.slice(0, 8) })}</p>
                  <p className="mt-2 text-[color:var(--fb-v2-text-muted)]">{tr("Ids and types only. Traces never contain message or document text.")}</p>
                  {TRACE_PARTS.map(([k, name]) => (
                    <div key={k} className="mt-3">
                      <p className="font-medium">{tr(name)}</p>
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-[color:var(--fb-v2-border)] p-2 text-xs">{JSON.stringify(trace[k] ?? [], null, 1)}</pre>
                    </div>
                  ))}
                </>
              ) : (
                <p className="text-[color:var(--fb-v2-text-muted)]">{tr("Pick a trace to see its context, tool calls and permission checks.")}</p>
              )}
            </aside>
          </div>
        </ScreenBody>
      ) : null}

      {tab === "Evaluations" ? (
        <>
          <form
            className="mb-6 grid gap-x-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 sm:grid-cols-3"
            onSubmit={(e) => {
              e.preventDefault();
              act(
                () =>
                  api.post(`/orgs/${orgId}/pulse/suites`, {
                    name: form.suite,
                    threshold: 80,
                    cases: [{ prompt: form.prompt, must_contain: form.contains ? form.contains.split(",").map((s) => s.trim()).filter(Boolean) : [] }],
                  }),
                tr("Suite created."),
                suites.reload,
              );
            }}
          >
            <Field label={tr("Suite name")}>
              <input className="v2-input" required value={form.suite} onChange={(e) => setForm({ ...form, suite: e.target.value })} />
            </Field>
            <Field label={tr("Prompt")}>
              <input className="v2-input" required value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} />
            </Field>
            <Field label={tr("Answer must contain")} hint={tr("Comma separated")}>
              <input className="v2-input" value={form.contains} onChange={(e) => setForm({ ...form, contains: e.target.value })} />
            </Field>
            <div>
              <Button type="submit">{tr("Create suite")}</Button>
            </div>
          </form>
          <ScreenBody state={suites.state} error={suites.error} emptyLabel={tr("No evaluation suites yet.")} onRetry={suites.reload}>
            <Rows>
              {rowsOf<Suite>(suites.data).map((s) => (
                <Row key={s.id}>
                  <div>
                    <p className="font-medium">{s.name}</p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("{n} case(s). Must pass {threshold}%.", { n: s.cases.length, threshold: s.threshold })}{" "}
                      {s.last_run
                        ? tr("Last run: {rate}% ({status}).", { rate: s.last_run.pass_rate ?? "–", status: label(STATUS, s.last_run.status) })
                        : tr("Never run.")}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {s.last_run ? (
                      <Button variant="ghost" onClick={() => api.get<Run>(`/orgs/${orgId}/pulse/runs/${s.last_run!.id}`).then(setRun)}>
                        {tr("Results")}
                      </Button>
                    ) : null}
                    <Button
                      variant="outline"
                      onClick={() =>
                        act(() => api.post<{ id: string }>(`/orgs/${orgId}/pulse/suites/${s.id}/run`), tr("Run started."), (r) => {
                          suites.reload();
                          api.get<Run>(`/orgs/${orgId}/pulse/runs/${r.id}`).then(setRun);
                        })
                      }
                    >
                      {tr("Run now")}
                    </Button>
                  </div>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
          {run ? (
            <Section title={tr("Run results: {rate}% (needs {threshold}%)", { rate: run.pass_rate ?? "–", threshold: run.threshold })}>
              <Rows>
                {run.results.map((r, i) => (
                  <Row key={i} className="items-start">
                    <div>
                      <p className="font-medium">{r.case}</p>
                      <ul className="text-sm">
                        {r.checks.map((c, j) => (
                          <li key={j} style={{ color: c.passed ? "var(--fb-v2-success)" : "var(--fb-v2-error)" }}>
                            {c.passed ? tr("Pass: {check}", { check: c.check }) : tr("Fail: {check}", { check: c.check })}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <Badge tone={r.passed ? "good" : "bad"}>{r.passed ? tr("Passed") : tr("Failed")}</Badge>
                  </Row>
                ))}
              </Rows>
            </Section>
          ) : null}
        </>
      ) : null}

      {tab === "Routing" ? (
        <ScreenBody state={policy.state} error={policy.error} onRetry={policy.reload}>
          <form
            className="max-w-xl rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              act(
                () =>
                  api.put(`/orgs/${orgId}/pulse/routing`, {
                    primary_model: form.primary || policy.data?.primary_model || "",
                    fallback_models: (form.fallbacks || (policy.data?.fallback_models ?? []).join(",")).split(",").map((s) => s.trim()).filter(Boolean),
                    latency_threshold_ms: form.latency ? Number(form.latency) : (policy.data?.latency_threshold_ms ?? null),
                  }),
                tr("Routing saved."),
                policy.reload,
              );
            }}
          >
            <Field label={tr("Primary model")} hint={tr("Now: {model}", { model: policy.data?.primary_model || tr("the server default") })}>
              <input className="v2-input" value={form.primary} onChange={(e) => setForm({ ...form, primary: e.target.value })} />
            </Field>
            <Field label={tr("Fall back to")} hint={tr("Comma separated. Now: {models}", { models: (policy.data?.fallback_models ?? []).join(", ") || tr("none") })}>
              <input className="v2-input" value={form.fallbacks} onChange={(e) => setForm({ ...form, fallbacks: e.target.value })} />
            </Field>
            <Field label={tr("Skip a model when its p95 latency is over (ms)")}>
              <input className="v2-input" inputMode="numeric" value={form.latency} onChange={(e) => setForm({ ...form, latency: e.target.value })} />
            </Field>
            <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Routing never applies to members' own keys, and a private-only policy always wins. AI actions always need approval.")}</p>
            <div className="flex gap-2">
              <Button type="submit">{tr("Save")}</Button>
              <Button type="button" variant="outline" onClick={() => api.get<typeof preview>(`/orgs/${orgId}/pulse/routing/preview`).then(setPreview)}>
                {tr("Preview")}
              </Button>
            </div>
          </form>
          {preview ? (
            <div className="mt-4 max-w-xl rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm">
              <p className="font-medium">{preview.model ? tr("A request now would use {model}.", { model: preview.model }) : preview.reason}</p>
              <ul className="mt-2 space-y-1">
                {(preview.steps ?? []).map((s, i) => (
                  <li key={i}>
                    {s.model}: {s.chosen ? tr("chosen") : tr("skipped, {reason}", { reason: s.skipped ?? "" })}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </ScreenBody>
      ) : null}

      {tab === "Alerts" ? (
        <>
          <form
            className="mb-6 flex flex-wrap items-end gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api.post(`/orgs/${orgId}/pulse/alerts`, { metric: form.metric, threshold: Number(form.threshold), window_minutes: 60 }), tr("Alert added."), alerts.reload);
            }}
          >
            <label className="text-sm">
              <span className="mb-1 block font-medium">{tr("Alert me when")}</span>
              <select className="v2-input w-56" value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })}>
                <option value="error_rate">{tr("the error rate (0 to 1)")}</option>
                <option value="p95_latency_ms">{tr("p95 latency in ms")}</option>
                <option value="daily_cost">{tr("AI cost in the window")}</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">{tr("goes above")}</span>
              <input className="v2-input w-28" inputMode="decimal" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })} />
            </label>
            <span className="pb-2 text-sm">{tr("within an hour")}</span>
            <Button type="submit">{tr("Add alert")}</Button>
          </form>
          <ScreenBody state={alerts.state} error={alerts.error} emptyLabel={tr("No alerts yet.")} onRetry={alerts.reload}>
            <Rows>
              {rowsOf<Alert>(alerts.data).map((a) => (
                <Row key={a.id}>
                  <span>
                    {tr("{metric} above {threshold} in {minutes} min", { metric: METRICS[a.metric] ? tr(METRICS[a.metric]) : a.metric.replace(/_/g, " "), threshold: a.threshold, minutes: a.window_minutes })}
                    {a.last_fired_at ? <span className="text-[color:var(--fb-v2-text-muted)]">{tr(". Last fired {when}", { when: when(a.last_fired_at) })}</span> : null}
                  </span>
                  <Button variant="ghost" onClick={() => act(() => api.del(`/orgs/${orgId}/pulse/alerts/${a.id}`), tr("Removed."), alerts.reload)}>
                    {tr("Remove")}
                  </Button>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </>
      ) : null}
    </div>
  );
}
