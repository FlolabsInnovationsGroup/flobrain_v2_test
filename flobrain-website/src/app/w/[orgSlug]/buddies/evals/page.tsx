"use client";

import { useEffect, useRef, useState } from "react";

import { CaseEditor } from "@/components/v2/evals/CaseEditor";
import { EMPTY_DRAFT, checkCount, draftFrom, inFlight, score, type EvalCase, type EvalSet, type Overview, type Policy, type RunSummary } from "@/components/v2/evals/evals";
import { GatePanel } from "@/components/v2/evals/GatePanel";
import { RunView } from "@/components/v2/evals/RunView";
import { ScoreTrend } from "@/components/v2/evals/ScoreTrend";
import { SuggestPanel } from "@/components/v2/evals/SuggestPanel";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { NoAccess } from "@/components/v2/states";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tab = "cases" | "runs" | "gate";
const TABS: Tab[] = ["cases", "runs", "gate"];

function RunBadge({ run }: { run: Pick<RunSummary, "status" | "passed"> }) {
  const tr = useTr();
  if (run.status === "queued" || run.status === "running") return <Badge>{tr("Running")}</Badge>;
  if (run.status === "error") return <Badge tone="bad">{tr("Did not run")}</Badge>;
  if (run.status === "stopped") return <Badge tone="bad">{tr("Stopped at budget")}</Badge>;
  return run.passed ? <Badge tone="good">{tr("Passed")}</Badge> : <Badge tone="bad">{tr("Below the pass mark")}</Badge>;
}

function NewSet({ orgId, buddyId, onMade }: { orgId: string; buddyId: string; onMade: (id: string) => void }) {
  const tr = useTr();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          const made = await api.post<EvalSet>(`/orgs/${orgId}/evals/sets`, { buddy: buddyId, name: name.trim(), threshold: 80 });
          setName("");
          onMade(made.id);
        } catch (err) {
          setError(errorText(err));
        }
      }}
    >
      <label className="text-sm">
        <span className="mb-1 block font-medium">{tr("New eval set")}</span>
        <input className="v2-input w-64 max-w-full" required maxLength={120} placeholder={tr("For example: Contract first reads")} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <Button type="submit" variant="outline">
        {tr("Create set")}
      </Button>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </form>
  );
}

function OrgSettings({ orgId, models }: { orgId: string; models: string[] }) {
  const tr = useTr();
  const { data, setData } = useOrgData<Policy>(orgId, "/evals/settings");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  if (!data) return null;
  return (
    <form
      className="grid gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 sm:grid-cols-2 lg:grid-cols-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setMessage(null);
        try {
          setData(await api.put<Policy>(`/orgs/${orgId}/evals/settings`, data));
          setMessage({ kind: "ok", text: tr("Eval settings saved.") });
        } catch (err) {
          setMessage({ kind: "error", text: errorText(err) });
        }
      }}
    >
      <label className="text-sm">
        <span className="mb-1 block font-medium">{tr("Judge model")}</span>
        <select className="v2-input w-full" value={data.judge_model} onChange={(e) => setData({ ...data, judge_model: e.target.value })}>
          <option value="">{tr("Same as your AI routing")}</option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">{tr("Most tokens per run")}</span>
        <input className="v2-input w-full" inputMode="numeric" value={data.max_run_tokens} onChange={(e) => setData({ ...data, max_run_tokens: Number(e.target.value) || 0 })} />
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">{tr("Most spend per run (USD)")}</span>
        <input className="v2-input w-full" inputMode="decimal" value={data.max_run_cost ?? ""} onChange={(e) => setData({ ...data, max_run_cost: e.target.value || null })} placeholder={tr("No limit")} />
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">{tr("Cases at the same time")}</span>
        <input className="v2-input w-full" type="number" min={1} max={8} value={data.concurrency} onChange={(e) => setData({ ...data, concurrency: Number(e.target.value) || 1 })} />
      </label>
      <p className="text-xs text-[color:var(--fb-v2-text-muted)] sm:col-span-2 lg:col-span-4">
        {tr("Runs also count against your org's AI budgets. When a run reaches its limit, the cases left are skipped and the run stops.")}
      </p>
      <div className="sm:col-span-2 lg:col-span-4">
        <Button type="submit" variant="outline">
          {tr("Save eval settings")}
        </Button>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      </div>
    </form>
  );
}

export default function BuddyEvalsPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const allowed = has(access, "evals.manage");
  const overview = useOrgData<Overview>(orgId, allowed ? "/evals/overview" : null);
  const [buddyChoice, setBuddyChoice] = useState<string | null>(null);
  const buddies = overview.data?.buddies ?? [];
  const buddyId = buddyChoice ?? buddies.find((b) => b.sets > 0)?.id ?? buddies[0]?.id ?? null;
  const sets = useOrgData<EvalSet[]>(orgId, buddyId ? `/evals/sets?buddy=${buddyId}` : null);
  const setRows = rowsOf<EvalSet>(sets.data);
  const [setChoice, setSetChoice] = useState<string | null>(null);
  const setId = setChoice && setRows.some((s) => s.id === setChoice) ? setChoice : (setRows[0]?.id ?? null);
  const detail = useOrgData<EvalSet>(orgId, setId ? `/evals/sets/${setId}` : null);
  const runs = useOrgData<RunSummary[]>(orgId, setId ? `/evals/sets/${setId}/runs` : null);
  const runRows = rowsOf<RunSummary>(runs.data);
  const [tab, setTab] = useState<Tab>("cases");
  const [runId, setRunId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [starting, setStarting] = useState(false);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const reloadDetail = detail.reload;
  const setRunsData = runs.setData;
  const setDetailData = detail.setData;
  const polling = inFlight(runRows);
  useEffect(() => {
    if (!polling || !orgId || !setId) return;
    const timer = setInterval(() => {
      api.get<RunSummary[]>(`/orgs/${orgId}/evals/sets/${setId}/runs`).then(setRunsData).catch(() => undefined);
      api.get<EvalSet>(`/orgs/${orgId}/evals/sets/${setId}`).then(setDetailData).catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
  }, [polling, orgId, setId, setRunsData, setDetailData]);

  if (access && !allowed) return <NoAccess />;
  const set = detail.data && detail.data.id === setId ? detail.data : null;
  const tools = overview.data?.tools ?? [];
  const toolLabel = (key: string) => tools.find((t) => t.key === key)?.label ?? key;

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      reloadDetail();
      sets.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function runNow() {
    if (!orgId || !setId) return;
    setStarting(true);
    setMessage(null);
    try {
      const run = await api.post<RunSummary>(`/orgs/${orgId}/evals/sets/${setId}/runs`);
      setTab("runs");
      setRunId(run.id);
      runs.reload();
      reloadDetail();
      overview.reload();
      setMessage({ kind: run.status === "error" ? "error" : "ok", text: run.status === "done" || run.status === "stopped" ? tr("Run finished: {s}.", { s: score(run.score) }) : run.status === "error" ? tr("The run could not start. Open it to see why.") : tr("Run started. Results appear here when it finishes.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setStarting(false);
    }
  }

  const tabLabel = (t: Tab) => (t === "cases" ? tr("Cases") : t === "runs" ? tr("Runs") : tr("Gate"));

  const caseRow = (c: EvalCase) =>
    editing === c.id && orgId ? (
      <li key={c.id} className="p-2">
        <CaseEditor
          orgId={orgId}
          tools={tools}
          initial={draftFrom(c)}
          onCancel={() => setEditing(null)}
          onSave={async (body) => {
            await api.patch(`/orgs/${orgId}/evals/cases/${c.id}`, body);
            setEditing(null);
            setMessage({ kind: "ok", text: tr("Case saved.") });
            reloadDetail();
          }}
        />
      </li>
    ) : (
      <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="font-medium" dir="auto">{c.name || c.input}</p>
          {c.name ? <p className="text-sm" dir="auto">{c.input}</p> : null}
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[color:var(--fb-v2-text-muted)]">
            <span>{tr("{n} checks", { n: checkCount(c) })}</span>
            {c.context_docs.length ? <span>{tr("{n} documents", { n: c.context_docs.length })}</span> : null}
            {c.expected_tool === "none" ? <span>{tr("No action")}</span> : c.expected_tool ? <span>{tr("Prepares {tool}", { tool: toolLabel(c.expected_tool) })}</span> : null}
            {c.language !== "any" ? <span>{c.language === "ar" ? tr("Arabic") : tr("English")}</span> : null}
            {c.rubric ? <span>{tr("AI judge")}</span> : null}
          </p>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" onClick={() => setEditing(c.id)} aria-label={tr("Edit “{q}”", { q: c.name || c.input })}>
            {tr("Edit")}
          </Button>
          <Button
            variant="ghost"
            aria-label={tr("Delete “{q}”", { q: c.name || c.input })}
            onClick={() => {
              if (window.confirm(tr("Delete this case?"))) void act(() => api.del(`/orgs/${orgId}/evals/cases/${c.id}`), tr("Case deleted."));
            }}
          >
            {tr("Delete")}
          </Button>
        </div>
      </li>
    );

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Buddy evals")}
        intro={tr("Test questions that prove a buddy is good before you publish or change it. Runs are a sandbox: nothing is sent, created or remembered.")}
      />
      <ScreenBody state={overview.state} error={overview.error} onRetry={overview.reload}>
        {buddies.length === 0 ? (
          <Notice>{tr("No buddies to test yet.")}</Notice>
        ) : (
          <>
            <div className="mb-6 flex flex-wrap items-end gap-4">
              <label className="text-sm">
                <span className="mb-1 block font-medium">{tr("Buddy")}</span>
                <select
                  className="v2-input w-72 max-w-full"
                  value={buddyId ?? ""}
                  onChange={(e) => {
                    setBuddyChoice(e.target.value);
                    setSetChoice(null);
                    setRunId(null);
                    setEditing(null);
                  }}
                >
                  {buddies.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                      {b.latest ? ` · ${score(b.latest.score)}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              {orgId && buddyId ? <NewSet orgId={orgId} buddyId={buddyId} onMade={(id) => { setSetChoice(id); sets.reload(); overview.reload(); }} /> : null}
            </div>

            {setRows.length ? (
              <ul className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label={tr("Eval sets")}>
                {setRows.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      aria-pressed={s.id === setId}
                      onClick={() => {
                        setSetChoice(s.id);
                        setRunId(null);
                        setEditing(null);
                      }}
                      className="flex w-full flex-col gap-1 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start ring-1 ring-inset ring-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] aria-pressed:ring-[color:var(--fb-v2-accent)]"
                    >
                      <span className="font-semibold">{s.name}</span>
                      <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
                        {tr("{n} cases", { n: s.cases_count })} · {tr("Pass mark {n}%", { n: s.threshold })}
                      </span>
                      <span className="mt-1 flex items-center gap-2">
                        <span className="font-mono text-lg tabular-nums">{score(s.latest_run?.score)}</span>
                        {s.latest_run ? <RunBadge run={s.latest_run} /> : <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Not run yet")}</span>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : sets.state === "ready" ? (
              <Notice>{tr("This buddy has no eval sets yet. Create one above.")}</Notice>
            ) : null}

            {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

            {set && orgId ? (
              <section aria-label={set.name}>
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-xl font-semibold">{set.name}</h2>
                    {set.description ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{set.description}</p> : null}
                    <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">
                      {set.baseline ? tr("Last accepted: {v} at {s}.", { v: set.baseline.version, s: score(set.baseline.score) }) : tr("No accepted version yet.")}{" "}
                      {set.gate_marketplace || set.gate_saves ? tr("The gate is on.") : tr("The gate is off.")}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => void runNow()} disabled={starting || polling || !set.cases_count}>
                      {starting || polling ? tr("Running…") : tr("Run now")}
                    </Button>
                    <Button variant="outline" onClick={() => { setSuggesting(true); setTab("cases"); }}>
                      {tr("Suggest cases")}
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => {
                        if (window.confirm(tr("Delete this set, its cases and its run history?"))) {
                          void act(() => api.del(`/orgs/${orgId}/evals/sets/${set.id}`), tr("Set deleted.")).then(() => {
                            setSetChoice(null);
                            overview.reload();
                          });
                        }
                      }}
                    >
                      {tr("Delete set")}
                    </Button>
                  </div>
                </div>

                <div
                  role="tablist"
                  aria-label={tr("Set sections")}
                  className="mb-4 inline-flex rounded-lg p-0.5 ring-1 ring-inset ring-[color:var(--fb-v2-border)]"
                  onKeyDown={(e) => {
                    const i = TABS.indexOf(tab);
                    const rtl = document.dir === "rtl";
                    const step = e.key === "ArrowRight" ? (rtl ? -1 : 1) : e.key === "ArrowLeft" ? (rtl ? 1 : -1) : 0;
                    if (!step) return;
                    e.preventDefault();
                    const next = TABS[(i + step + TABS.length) % TABS.length];
                    setTab(next);
                    tabRefs.current[TABS.indexOf(next)]?.focus();
                  }}
                >
                  {TABS.map((t, i) => (
                    <button
                      key={t}
                      ref={(el) => {
                        tabRefs.current[i] = el;
                      }}
                      type="button"
                      role="tab"
                      id={`evals-tab-${t}`}
                      aria-controls={`evals-panel-${t}`}
                      aria-selected={tab === t}
                      tabIndex={tab === t ? 0 : -1}
                      onClick={() => setTab(t)}
                      className="rounded-md px-3 py-1.5 text-sm font-medium text-[color:var(--fb-v2-text-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] aria-selected:bg-[color:var(--fb-v2-accent)] aria-selected:text-white"
                    >
                      {tabLabel(t)}
                    </button>
                  ))}
                </div>

                <div role="tabpanel" id={`evals-panel-${tab}`} aria-labelledby={`evals-tab-${tab}`}>
                  {tab === "cases" ? (
                    <div className="flex flex-col gap-4">
                      {suggesting ? (
                        <SuggestPanel
                          orgId={orgId}
                          setId={set.id}
                          tools={tools}
                          onClose={() => setSuggesting(false)}
                          onSaved={(n) => {
                            setSuggesting(false);
                            setMessage({ kind: "ok", text: tr("{n} cases added.", { n }) });
                            reloadDetail();
                            sets.reload();
                          }}
                        />
                      ) : null}
                      {set.cases?.length ? <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">{set.cases.map(caseRow)}</ul> : <Notice>{tr("No cases yet. Add one, or let the AI suggest some.")}</Notice>}
                      {editing === "new" ? (
                        <CaseEditor
                          orgId={orgId}
                          tools={tools}
                          initial={EMPTY_DRAFT}
                          onCancel={() => setEditing(null)}
                          onSave={async (body) => {
                            await api.post(`/orgs/${orgId}/evals/sets/${set.id}/cases`, body);
                            setEditing(null);
                            setMessage({ kind: "ok", text: tr("Case added.") });
                            reloadDetail();
                            sets.reload();
                          }}
                        />
                      ) : (
                        <div>
                          <Button variant="outline" onClick={() => setEditing("new")}>
                            {tr("Add a case")}
                          </Button>
                        </div>
                      )}
                    </div>
                  ) : null}

                  {tab === "runs" ? (
                    <div className="flex flex-col gap-6">
                      <ScoreTrend trend={set.trend ?? []} threshold={set.threshold} />
                      {runRows.length ? (
                        <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
                          <table className="w-full min-w-[40rem] text-sm">
                            <caption className="sr-only">{tr("Run history")}</caption>
                            <thead className="text-[color:var(--fb-v2-text-muted)]">
                              <tr>
                                <th scope="col" className="px-4 py-2 text-start font-medium">{tr("When")}</th>
                                <th scope="col" className="px-3 py-2 text-start font-medium">{tr("Version")}</th>
                                <th scope="col" className="px-3 py-2 text-start font-medium">{tr("Started by")}</th>
                                <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Score")}</th>
                                <th scope="col" className="px-3 py-2 text-start font-medium">{tr("Result")}</th>
                                <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Tokens")}</th>
                                <th scope="col" className="px-4 py-2 text-end font-medium">{tr("Cost")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {runRows.map((r) => (
                                <tr key={r.id} className={`border-t border-[color:var(--fb-v2-border)] ${r.id === runId ? "bg-[color:var(--fb-v2-accent-soft)]" : ""}`}>
                                  <th scope="row" className="px-4 py-2 text-start font-normal">
                                    <button type="button" className="text-start underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]" onClick={() => setRunId(r.id)}>
                                      {when(r.created_at)}
                                    </button>
                                  </th>
                                  <td className="px-3 py-2">{r.version}</td>
                                  <td className="px-3 py-2">
                                    {r.triggered_by === "gate" ? tr("Gate check") : r.triggered_by === "schedule" ? tr("Scheduled") : r.by?.name ?? tr("Run by hand")}
                                  </td>
                                  <td className="px-3 py-2 text-end font-mono tabular-nums">{score(r.score)}</td>
                                  <td className="px-3 py-2">
                                    <RunBadge run={r} /> <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{r.cases_passed}/{r.cases_total}</span>
                                  </td>
                                  <td className="px-3 py-2 text-end tabular-nums">{r.tokens.toLocaleString()}</td>
                                  <td className="px-4 py-2 text-end tabular-nums">${Number(r.cost).toFixed(4)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                      {runId ? (
                        <section aria-label={tr("Run results")}>
                          <h3 className="mb-2 font-semibold">{tr("Expected and what the buddy did")}</h3>
                          <RunView key={runId} orgId={orgId} runId={runId} />
                        </section>
                      ) : runRows.length ? (
                        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Pick a run to see each case.")}</p>
                      ) : null}
                    </div>
                  ) : null}

                  {tab === "gate" ? <GatePanel key={set.id} orgId={orgId} set={set} onSaved={() => { reloadDetail(); sets.reload(); }} /> : null}
                </div>
              </section>
            ) : null}

            {orgId ? (
              <Section title={tr("Eval settings for your org")}>
                <OrgSettings orgId={orgId} models={overview.data?.judge_models ?? []} />
              </Section>
            ) : null}
          </>
        )}
      </ScreenBody>
    </div>
  );
}
