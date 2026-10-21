export type MissionMetrics = {
  assigned_open: number;
  assigned_done: number;
  blocked: number;
  overdue: number;
};

export type WorkloadRow = {
  user_id: string;
  open_tasks: number;
  done_tasks: number;
  seconds_7d: number;
  task_ids: string[];
};

export function isMissionControlEmpty(data: {
  accomplishments?: unknown[];
  blockers?: unknown[];
  deadlines?: unknown[];
  workload?: unknown[];
  assigned_open?: number;
}): boolean {
  return (
    !(data.accomplishments?.length || data.blockers?.length || data.deadlines?.length) &&
    (data.assigned_open ?? 0) === 0 &&
    !(data.workload ?? []).some((row) => (row as WorkloadRow).open_tasks > 0)
  );
}

export function workloadDrilldown(rows: WorkloadRow[], userId: string | null): WorkloadRow | null {
  if (!userId) return null;
  return rows.find((row) => row.user_id === userId) ?? null;
}

export function formatBlockedDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

export function metricCards(data: MissionMetrics) {
  return [
    { id: "open", label: "Open", value: data.assigned_open },
    { id: "done", label: "Done", value: data.assigned_done },
    { id: "blocked", label: "Blocked", value: data.blocked },
    { id: "overdue", label: "Overdue", value: data.overdue },
  ];
}
