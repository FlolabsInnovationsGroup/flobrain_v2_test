import type { Step, StepType, Trigger, TriggerType } from "./steps";

export type Tr = (text: string, vars?: Record<string, string | number>) => string;

export type RunStatus = "queued" | "running" | "waiting_approval" | "done" | "failed" | "cancelled";

export type WorkflowRow = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  trigger: Trigger;
  trigger_label: string;
  steps: Step[];
  template_key: string;
  run_as: { id: string; name: string } | null;
  last_run_at: string | null;
  next_run_at: string | null;
  last_run: { id: string; status: RunStatus; created_at: string } | null;
  waiting_runs: number;
  hook: { path: string; secret_hint: string; last_received_at: string | null } | null;
  can_manage: boolean;
};

export type StepLogEntry = {
  step: number;
  type: StepType;
  label: string;
  status: "done" | "waiting" | "failed" | "skipped" | "started";
  output: string | null;
  detail: Record<string, unknown>;
  at: string;
};

export type Run = {
  id: string;
  workflow: string;
  workflow_name: string;
  status: RunStatus;
  reason: string;
  triggered_by: string | null;
  error: string;
  current_step: number;
  steps_total: number;
  waiting_approval: string | null;
  created_at: string;
  finished_at: string | null;
  step_log?: StepLogEntry[];
};

export type Template = {
  key: string;
  name: string;
  description: string;
  category: string;
  needs: ("room" | "emails")[];
  proactive: boolean;
  installed: boolean;
  trigger: Trigger;
  steps: Step[];
};

export type RoomOption = { id: string; name: string; kind?: string };

export function stepTypeLabel(tr: Tr, type: StepType): string {
  switch (type) {
    case "ai_prompt":
      return tr("Ask the AI");
    case "post_to_room":
      return tr("Post in a room");
    case "create_task":
      return tr("Create a task");
    case "notify":
      return tr("Notify people");
    case "send_email":
      return tr("Send an email");
    case "call_webhook":
      return tr("Call a webhook");
    case "wait_for_approval":
      return tr("Wait for approval");
    case "daily_brief":
      return tr("Send everyone their daily brief");
    case "nudge_overdue":
      return tr("Nudge owners of overdue tasks");
    case "check_budget":
      return tr("Check the AI budget");
  }
}

export function triggerTypeLabel(tr: Tr, type: TriggerType): string {
  switch (type) {
    case "manual":
      return tr("Only when run by hand");
    case "schedule":
      return tr("On a schedule");
    case "room_message":
      return tr("When a room message has a word");
    case "task_created":
      return tr("When a task is created");
    case "task_blocked":
      return tr("When a task is blocked");
    case "meeting_ended":
      return tr("When a meeting ends");
    case "customer_conversation":
      return tr("When a customer conversation starts");
    case "webhook":
      return tr("When another system calls its webhook");
  }
}

export function runStatusLabel(tr: Tr, status: RunStatus): string {
  switch (status) {
    case "queued":
      return tr("Queued");
    case "running":
      return tr("Running");
    case "waiting_approval":
      return tr("Waiting for approval");
    case "done":
      return tr("Done");
    case "failed":
      return tr("Failed");
    case "cancelled":
      return tr("Cancelled");
  }
}

/** Mission control colours: amber only while waiting for approval, rose only for failures. */
export function runTone(status: RunStatus): "waiting" | "good" | "bad" | "neutral" {
  if (status === "waiting_approval") return "waiting";
  if (status === "done") return "good";
  if (status === "failed") return "bad";
  return "neutral";
}

export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const;

export function weekdayLabel(tr: Tr, day: number): string {
  return [tr("Monday"), tr("Tuesday"), tr("Wednesday"), tr("Thursday"), tr("Friday"), tr("Saturday"), tr("Sunday")][day] ?? "";
}

export function roleLabel(tr: Tr, role: string): string {
  switch (role) {
    case "owner":
      return tr("The person it runs as");
    case "admins":
      return tr("Admins");
    case "team_leads":
      return tr("The task's team lead");
    case "task_assignees":
      return tr("The task's assignees");
    case "room_members":
      return tr("The room's members");
    default:
      return role;
  }
}

export function contextLabel(tr: Tr, context: string): string {
  switch (context) {
    case "none":
      return tr("No workspace data");
    case "blocked_tasks":
      return tr("Blocked tasks");
    case "overdue_tasks":
      return tr("Overdue tasks");
    case "tasks_due_today":
      return tr("Tasks due today");
    case "recent_tasks":
      return tr("Tasks changed in the last 7 days");
    case "trigger":
      return tr("What started the workflow");
    default:
      return context;
  }
}
