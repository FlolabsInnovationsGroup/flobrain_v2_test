"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { clampPercent, score, type EvalSet, type GateEvent, type GateResult, type GateSetRow } from "./evals";

/** One set's line in a gate report, worded here so it is translated. */
export function GateLine({ row }: { row: GateSetRow }) {
  const tr = useTr();
  let text: string;
  if (row.status !== "done" || row.score === null) text = tr("The checks could not finish.");
  else if (row.score < row.threshold) text = tr("Score {s} is below the pass mark of {t}%.", { s: score(row.score), t: row.threshold });
  else if (row.previous !== null && row.previous - row.score > row.max_drop)
    text = tr("Score {s} is {d} points below the previous version ({p}).", { s: score(row.score), d: (row.previous - row.score).toFixed(1), p: score(row.previous) });
  else text = tr("Score {s}, pass mark {t}%.", { s: score(row.score), t: row.threshold });
  return (
    <li className="text-sm">
      <span className="font-medium">{row.name}</span>: {text}
      {row.failed_cases.length ? (
        <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Failed cases: {list}", { list: row.failed_cases.join(", ") })}</span>
      ) : null}
    </li>
  );
}

function OutcomeBadge({ outcome }: { outcome: GateEvent["outcome"] | GateResult["outcome"] }) {
  const tr = useTr();
  if (outcome === "passed") return <Badge tone="good">{tr("Passed")}</Badge>;
  if (outcome === "blocked") return <Badge tone="bad">{tr("Blocked")}</Badge>;
  if (outcome === "overridden") return <Badge tone="accent">{tr("Overridden")}</Badge>;
  return <Badge>{tr("Not checked")}</Badge>;
}

export function GatePanel({ orgId, set, onSaved }: { orgId: string; set: EvalSet; onSaved: () => void }) {
  const tr = useTr();
  const [threshold, setThreshold] = useState(String(set.threshold));
  const [maxDrop, setMaxDrop] = useState(String(set.max_drop));
  const [market, setMarket] = useState(set.gate_marketplace);
  const [saves, setSaves] = useState(set.gate_saves);
  const [schedule, setSchedule] = useState(set.schedule);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<GateResult | null>(null);
  const { data: events, reload } = useOrgData<GateEvent[]>(orgId, `/evals/gate-events?buddy=${set.buddy.id}`);

  async function save() {
    setMessage(null);
    try {
      await api.patch(`/orgs/${orgId}/evals/sets/${set.id}`, {
        threshold: clampPercent(threshold, set.threshold),
        max_drop: clampPercent(maxDrop, set.max_drop),
        gate_marketplace: market,
        gate_saves: saves,
        schedule,
      });
      setMessage({ kind: "ok", text: tr("Gate settings saved.") });
      onSaved();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function checkNow() {
    setChecking(true);
    setResult(null);
    setMessage(null);
    try {
      setResult(await api.post<GateResult>(`/orgs/${orgId}/evals/gate-check`, { buddy: set.buddy.id }));
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setChecking(false);
    }
  }

  const label = "mb-1 block text-sm font-medium";
  return (
    <div className="flex flex-col gap-6">
      <form
        className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className={label} htmlFor="gate-threshold">{tr("Pass mark (%)")}</label>
            <input id="gate-threshold" className="v2-input w-full" inputMode="numeric" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="gate-drop">{tr("Allowed drop (points)")}</label>
            <input id="gate-drop" className="v2-input w-full" inputMode="numeric" value={maxDrop} onChange={(e) => setMaxDrop(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="gate-schedule">{tr("Run on a schedule")}</label>
            <select id="gate-schedule" className="v2-input w-full" value={schedule} onChange={(e) => setSchedule(e.target.value as EvalSet["schedule"])}>
              <option value="off">{tr("Off")}</option>
              <option value="daily">{tr("Every day")}</option>
              <option value="weekly">{tr("Every week")}</option>
            </select>
          </div>
        </div>
        <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
          {tr("A change is blocked when its score is under the pass mark, or more points under the last accepted version than the allowed drop.")}
        </p>
        <fieldset className="mt-4 space-y-2">
          <legend className={label}>{tr("When to check")}</legend>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={market} onChange={(e) => setMarket(e.target.checked)} />
            <span>{tr("Before it is offered in the marketplace, and before each new version")}</span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={saves} onChange={(e) => setSaves(e.target.checked)} />
            <span>{tr("Block saves that drop the score below the pass mark")}</span>
          </label>
        </fieldset>
        <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
          {tr("Someone who manages evals can still go ahead with a written reason. Every block and override is in the audit log.")}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="submit">{tr("Save gate settings")}</Button>
          <Button type="button" variant="outline" disabled={checking} onClick={() => void checkNow()}>
            {checking ? tr("Checking…") : tr("Check the buddy now")}
          </Button>
        </div>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      </form>

      {result ? (
        <section aria-live="polite" className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
          <div className="mb-2 flex items-center gap-2">
            <OutcomeBadge outcome={result.outcome} />
            <span className="text-sm">
              {result.outcome === "skipped"
                ? tr("No set guards this buddy yet. Turn on a check above.")
                : result.allowed
                  ? tr("The buddy would pass the gate.")
                  : tr("The buddy would be blocked.")}
            </span>
          </div>
          <ul className="space-y-1">
            {result.sets.map((row) => (
              <GateLine key={row.set} row={row} />
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h3 className="mb-2 font-semibold">{tr("Gate history")}</h3>
        {rowsOf<GateEvent>(events).length ? (
          <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
            {rowsOf<GateEvent>(events).map((e) => (
              <li key={e.id} className="flex flex-col gap-1 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <OutcomeBadge outcome={e.outcome} />
                  <span>{e.context === "marketplace" ? tr("Marketplace") : e.context === "save" ? tr("Buddy edit") : tr("Check")}</span>
                  <span className="text-[color:var(--fb-v2-text-muted)]">
                    {when(e.created_at)}
                    {e.by ? ` · ${e.by.name}` : ""}
                  </span>
                </div>
                <ul className="space-y-1">
                  {e.details.map((row) => (
                    <GateLine key={row.set + row.run} row={row} />
                  ))}
                </ul>
                {e.override_reason ? <p className="text-sm">{tr("Reason: {reason}", { reason: e.override_reason })}</p> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("The gate has not checked this buddy yet.")}</p>
        )}
      </section>
    </div>
  );
}
