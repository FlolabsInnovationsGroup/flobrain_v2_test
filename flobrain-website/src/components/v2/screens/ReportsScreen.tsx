"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import { weeklyTotalMatchesEntries } from "@/lib/v2/screens/reports";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function ReportsScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [seconds, setSeconds] = useState(0);
  const [entries, setEntries] = useState(0);
  const [matches, setMatches] = useState(true);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    Promise.all([v2Client().reportMe(orgId, "week"), v2Client().timeEntries(orgId)])
      .then(([report, list]) => {
        setSeconds(report.seconds);
        setEntries(report.entries);
        const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
        const weekEntries = (list.results ?? []).filter((entry) => {
          if (!entry.started_at) return true;
          return new Date(entry.started_at).getTime() >= weekAgo;
        });
        setMatches(weeklyTotalMatchesEntries(report, weekEntries));
        setState(report.entries === 0 ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load reports");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Weekly report</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No time logged this week" onRetry={load}>
        <p>{seconds} seconds across {entries} entries</p>
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
          {matches ? "Totals match time entries" : "Totals do not match time entries"}
        </p>
      </ScreenBody>
    </section>
  );
}
