"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import {
  formatBlockedDuration,
  isMissionControlEmpty,
  metricCards,
  workloadDrilldown,
  type WorkloadRow,
} from "@/lib/v2/screens/missionControl";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

type Payload = {
  assigned_open: number;
  assigned_done: number;
  blocked: number;
  overdue: number;
  accomplishments: Array<{ id: string; title: string; done_at: string; assignees: string[] }>;
  blockers: Array<{ id: string; title: string; blocked_seconds: number; assignees: string[] }>;
  deadlines: Array<{ id: string; title: string; due_on: string; priority: string; assignees: string[] }>;
  workload: WorkloadRow[];
};

export function MissionControlScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [data, setData] = useState<Payload | null>(null);
  const [drill, setDrill] = useState<string | null>(null);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .missionControl(orgId)
      .then((raw) => {
        const payload = raw as Payload;
        setData(payload);
        setState(isMissionControlEmpty(payload) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load Mission Control");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  const selected = data ? workloadDrilldown(data.workload, drill) : null;

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Mission Control</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No team activity yet" onRetry={load}>
        {data ? (
          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-4">
              {metricCards(data).map((card) => (
                <div key={card.id} className="rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-surface)] p-3">
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{card.label}</p>
                  <p className="text-2xl font-semibold">{card.value}</p>
                </div>
              ))}
            </div>
            <section>
              <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">
                Top accomplishments
              </h2>
              <ul className="space-y-1">
                {data.accomplishments.map((item) => (
                  <li key={item.id}>
                    {item.title} · {item.done_at.slice(0, 10)}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Blockers</h2>
              <ul className="space-y-1">
                {data.blockers.map((item) => (
                  <li key={item.id}>
                    {item.title} · {formatBlockedDuration(item.blocked_seconds)}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Deadlines</h2>
              <ul className="space-y-1">
                {data.deadlines.map((item) => (
                  <li key={item.id}>
                    {item.title} · {item.due_on} · {item.priority}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Workload</h2>
              <ul className="space-y-1">
                {data.workload.map((row) => (
                  <li key={row.user_id}>
                    <button type="button" className="text-[color:var(--fb-v2-accent)]" onClick={() => setDrill(row.user_id)}>
                      {row.user_id.slice(0, 8)} · {row.open_tasks} open · {Math.round(row.seconds_7d / 3600)}h
                    </button>
                  </li>
                ))}
              </ul>
              {selected ? (
                <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                  Tasks: {selected.task_ids.join(", ") || "none"}
                </p>
              ) : null}
            </section>
          </div>
        ) : null}
      </ScreenBody>
    </section>
  );
}
