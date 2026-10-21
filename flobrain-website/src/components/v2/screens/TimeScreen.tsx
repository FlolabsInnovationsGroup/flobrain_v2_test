"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { TopBarTimer } from "@/components/v2/timer/TopBarTimer";
import { v2Client } from "@/lib/v2/client";
import { isEmptyList, screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function TimeScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [entries, setEntries] = useState<Array<{ id?: string; description?: string; seconds: number }>>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .timeEntries(orgId)
      .then((data) => {
        setEntries(data.results ?? []);
        setState(screenStateFromHttp(200, isEmptyList(data)));
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load time entries");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Time</h1>
        <TopBarTimer orgId={orgId} />
      </div>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No time entries yet" onRetry={load}>
        <ul className="space-y-2">
          {entries.map((entry, index) => (
            <li key={entry.id ?? index}>
              {entry.description || "Time entry"} · {entry.seconds}s
            </li>
          ))}
        </ul>
      </ScreenBody>
    </section>
  );
}
