"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import { impactScoreLabel } from "@/lib/v2/screens/metrics";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function CockpitScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [impact, setImpact] = useState<number | null>(null);
  const [pins, setPins] = useState<Array<{ id: string; body: string }>>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    Promise.all([v2Client().dashboardMe(orgId), v2Client().announcements(orgId)])
      .then(([data, announcements]) => {
        setImpact(data.impact_score ?? null);
        setPins(announcements as Array<{ id: string; body: string }>);
        setState("ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load cockpit");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Cockpit</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No data yet" onRetry={load}>
        <div className="space-y-4">
          <div className="rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-surface)] p-3">
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">Impact score</p>
            <p className="text-2xl font-semibold">{impactScoreLabel(impact)}</p>
          </div>
          <section>
            <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Announcements</h2>
            {pins.length === 0 ? (
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">No announcements</p>
            ) : (
              <ul className="space-y-1">
                {pins.map((pin) => (
                  <li key={pin.id}>{pin.body}</li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </ScreenBody>
    </section>
  );
}
