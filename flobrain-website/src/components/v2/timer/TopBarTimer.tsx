"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import { applyTimerResponse, emptyTimer, timerLabel } from "@/lib/v2/screens/timer";

export function TopBarTimer({ orgId }: { orgId?: string | null }) {
  const [snapshot, setSnapshot] = useState(emptyTimer());

  useEffect(() => {
    if (!orgId) return;
    v2Client()
      .timer(orgId)
      .then((data) => setSnapshot(applyTimerResponse(emptyTimer(), { type: "loaded", running: data.running })))
      .catch(() => undefined);
  }, [orgId]);

  async function toggle() {
    if (!orgId) return;
    try {
      if (snapshot.running) {
        await v2Client().stopTimer(orgId);
        setSnapshot(applyTimerResponse(snapshot, { type: "stopped" }));
        return;
      }
      const started = await v2Client().startTimer(orgId);
      setSnapshot(
        applyTimerResponse(snapshot, {
          type: "started",
          running: { id: started.id, description: started.description || "" },
        }),
      );
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        const running = await v2Client().timer(orgId);
        setSnapshot(applyTimerResponse(snapshot, { type: "conflict", running: running.running }));
      }
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{timerLabel(snapshot)}</span>
      <Button type="button" variant="ghost" onClick={toggle} disabled={!orgId}>
        {snapshot.running ? "Stop" : "Start"}
      </Button>
    </div>
  );
}
