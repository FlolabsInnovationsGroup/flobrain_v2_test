export type RunningTimer = {
  id: string;
  description: string;
  started_at?: string;
  category?: string;
  task?: string | null;
  task_title?: string;
};

export type TimerSnapshot = {
  running: RunningTimer | null;
  conflict: boolean;
};

export function emptyTimer(): TimerSnapshot {
  return { running: null, conflict: false };
}

export function applyTimerResponse(
  current: TimerSnapshot,
  event: { type: "loaded" | "started" | "stopped" | "conflict"; running?: TimerSnapshot["running"] },
): TimerSnapshot {
  if (event.type === "conflict") return { running: event.running ?? current.running, conflict: true };
  if (event.type === "stopped") return { running: null, conflict: false };
  return { running: event.running ?? current.running, conflict: false };
}

export function timerLabel(snapshot: TimerSnapshot): string {
  if (snapshot.conflict) return "Timer already running";
  return snapshot.running ? "Timer running" : "Timer stopped";
}

/** Clock difference between server and browser in ms (server minus browser). */
export function clockSkew(serverTime: string | undefined, browserNow: number): number {
  if (!serverTime) return 0;
  const server = new Date(serverTime).getTime();
  return Number.isNaN(server) ? 0 : server - browserNow;
}

/** Seconds the running timer has been on, using the server's clock (Decision: server is the clock). */
export function elapsedSeconds(running: RunningTimer | null, browserNow: number, skewMs = 0): number {
  if (!running?.started_at) return 0;
  const start = new Date(running.started_at).getTime();
  if (Number.isNaN(start)) return 0;
  return Math.max(0, Math.floor((browserNow + skewMs - start) / 1000));
}
