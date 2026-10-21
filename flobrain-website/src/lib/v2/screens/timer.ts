export type TimerSnapshot = {
  running: { id: string; description: string } | null;
  conflict: boolean;
};

export function emptyTimer(): TimerSnapshot {
  return { running: null, conflict: false };
}

export function applyTimerResponse(
  current: TimerSnapshot,
  event: { type: "loaded" | "started" | "stopped" | "conflict"; running?: TimerSnapshot["running"] },
): TimerSnapshot {
  if (event.type === "conflict") return { ...current, conflict: true };
  if (event.type === "stopped") return { running: null, conflict: false };
  return { running: event.running ?? current.running, conflict: false };
}

export function timerLabel(snapshot: TimerSnapshot): string {
  if (snapshot.conflict) return "Timer already running";
  return snapshot.running ? "Timer running" : "Timer stopped";
}
