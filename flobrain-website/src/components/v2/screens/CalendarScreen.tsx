"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import { groupCalendarByDate, type CalendarItem } from "@/lib/v2/screens/calendar";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function CalendarScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .calendar(orgId)
      .then((data) => {
        setItems(data);
        setState(data.length === 0 ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load calendar");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  const grouped = useMemo(() => groupCalendarByDate(items), [items]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Calendar</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No deadlines yet" onRetry={load}>
        <div className="space-y-4">
          {Object.entries(grouped).map(([date, rows]) => (
            <section key={date}>
              <h2 className="text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">{date}</h2>
              <ul>
                {rows.map((item) => (
                  <li key={item.id}>{item.title}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </ScreenBody>
    </section>
  );
}
