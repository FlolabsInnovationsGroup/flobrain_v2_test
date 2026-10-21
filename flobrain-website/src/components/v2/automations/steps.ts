/**
 * Pure logic for the workflow step-list editor: defaults per step type, add, remove and move
 * (keeping `{{steps.N.output}}` references pointing at the same step), and quick client checks.
 * The server validates everything again; these checks only help people fix things early.
 */

export type TriggerType =
  | "manual"
  | "schedule"
  | "room_message"
  | "task_created"
  | "task_blocked"
  | "meeting_ended"
  | "customer_conversation"
  | "webhook";

export type Trigger = {
  type: TriggerType;
  every?: "day" | "week" | "month" | "hours";
  at?: string;
  weekday?: number;
  day?: number;
  hours?: number;
  timezone?: string;
  room?: string;
  keyword?: string;
  team?: string;
};

export type StepType =
  | "ai_prompt"
  | "post_to_room"
  | "create_task"
  | "notify"
  | "send_email"
  | "call_webhook"
  | "wait_for_approval"
  | "daily_brief"
  | "nudge_overdue"
  | "check_budget";

export type Step = { type: StepType; label?: string } & Record<string, unknown>;

export type Workflow = {
  id?: string;
  name: string;
  description?: string;
  enabled?: boolean;
  trigger: Trigger;
  steps: Step[];
};

export const MAX_STEPS = 12;

export const STEP_TYPES: StepType[] = [
  "ai_prompt",
  "post_to_room",
  "create_task",
  "notify",
  "send_email",
  "call_webhook",
  "wait_for_approval",
  "daily_brief",
  "nudge_overdue",
  "check_budget",
];

/** Steps that leave FloBrain and always wait for an approval (webhooks skip it for trusted hosts). */
export const NEEDS_APPROVAL: StepType[] = ["send_email", "call_webhook", "wait_for_approval"];

export const ROLES = ["owner", "admins", "team_leads", "task_assignees", "room_members"] as const;

export const ROOM_TRIGGERS: TriggerType[] = ["room_message", "meeting_ended"];

export function defaultStep(type: StepType, previous: number): Step {
  const ref = previous > 0 ? `{{steps.${previous}.output}}` : "";
  switch (type) {
    case "ai_prompt":
      return { type, prompt: "", context: "none" };
    case "post_to_room":
      return { type, room: "", text: ref };
    case "create_task":
      return { type, title: "", due_in_days: 3 };
    case "notify":
      return { type, roles: ["owner"], text: ref || "" };
    case "send_email":
      return { type, to: [], subject: "", body: ref };
    case "call_webhook":
      return { type, url: "https://", method: "POST", body: ref };
    case "wait_for_approval":
      return { type, message: "" };
    case "nudge_overdue":
      return { type, min_days_overdue: 1 };
    case "check_budget":
      return { type, threshold_pct: 80 };
    default:
      return { type };
  }
}

export function defaultTrigger(type: TriggerType): Trigger {
  if (type === "schedule") return { type, every: "day", at: "09:00" };
  if (type === "room_message") return { type, room: "", keyword: "" };
  return { type };
}

const REF = /\{\{\s*steps\.(\d+)\.output\s*\}\}/g;

/** Rewrite `{{steps.N.output}}` in every string field with `map(N)`; `null` drops the reference. */
function remap(steps: Step[], map: (n: number) => number | null): Step[] {
  return steps.map((step) => {
    const next: Step = { ...step };
    for (const [key, value] of Object.entries(step)) {
      if (typeof value === "string" && value.includes("{{")) {
        next[key] = value.replace(REF, (whole, n: string) => {
          const to = map(Number(n));
          return to === null ? "" : `{{steps.${to}.output}}`;
        });
      }
    }
    return next;
  });
}

export function addStep(steps: Step[], type: StepType): Step[] {
  if (steps.length >= MAX_STEPS) return steps;
  return [...steps, defaultStep(type, steps.length)];
}

export function removeStep(steps: Step[], index: number): Step[] {
  if (index < 0 || index >= steps.length) return steps;
  const removed = index + 1;
  const kept = steps.filter((_, i) => i !== index);
  return remap(kept, (n) => (n === removed ? null : n > removed ? n - 1 : n));
}

/** Move the step at `from` to `to` (0-based); references follow the steps they point at. */
export function moveStep(steps: Step[], from: number, to: number): Step[] {
  if (from === to || from < 0 || to < 0 || from >= steps.length || to >= steps.length) return steps;
  const order = steps.map((_, i) => i);
  const [picked] = order.splice(from, 1);
  order.splice(to, 0, picked);
  const newPosition = new Map(order.map((old, i) => [old + 1, i + 1]));
  return remap(
    order.map((old) => steps[old]),
    (n) => newPosition.get(n) ?? n,
  );
}

export function updateStep(steps: Step[], index: number, patch: Record<string, unknown>): Step[] {
  return steps.map((step, i) => (i === index ? ({ ...step, ...patch } as Step) : step));
}

/** Short, local problems per step (index -> messages), in English for `tr()`. */
export function stepIssues(steps: Step[], trigger: Trigger): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  const add = (i: number, text: string) => {
    (out[i] ??= []).push(text);
  };
  steps.forEach((step, i) => {
    for (const [, value] of Object.entries(step)) {
      if (typeof value !== "string") continue;
      for (const match of value.matchAll(REF)) {
        const n = Number(match[1]);
        if (n < 1 || n > i) add(i, "Uses the answer of a step that doesn't come before it.");
      }
    }
    const text = (key: string) => String(step[key] ?? "").trim();
    if (step.type === "ai_prompt" && !text("prompt")) add(i, "Write what the AI should do.");
    if (step.type === "post_to_room") {
      if (!text("room")) add(i, "Pick a room.");
      if (step.room === "trigger" && !ROOM_TRIGGERS.includes(trigger.type)) add(i, "\"The trigger's room\" only works with room message and meeting triggers.");
      if (!text("text")) add(i, "Write the message.");
    }
    if (step.type === "create_task" && !text("title")) add(i, "Give the task a title.");
    if (step.type === "notify") {
      if (!text("text")) add(i, "Write the notification.");
      const roles = Array.isArray(step.roles) ? step.roles : [];
      const people = Array.isArray(step.people) ? step.people : [];
      if (!roles.length && !people.length) add(i, "Pick who to notify.");
    }
    if (step.type === "send_email") {
      const to = Array.isArray(step.to) ? step.to : [];
      if (!to.length) add(i, "Add at least one email address.");
      if (!text("subject")) add(i, "Write a subject.");
    }
    if (step.type === "call_webhook" && !/^https:\/\/[^/\s]+/.test(text("url"))) add(i, "Use an https address.");
    if (step.type === "wait_for_approval" && !text("message")) add(i, "Say what you are approving.");
  });
  return out;
}

export function triggerIssues(trigger: Trigger): string[] {
  const out: string[] = [];
  if (trigger.type === "schedule") {
    if (trigger.every !== "hours" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(trigger.at ?? "")) out.push("Use a time like 09:00.");
  }
  if (trigger.type === "room_message") {
    if (!trigger.room) out.push("Pick a room.");
    if ((trigger.keyword ?? "").trim().length < 2) out.push("Type a word to listen for.");
  }
  return out;
}

/** The body sent to the API: trims empty optional fields so the strict server schema accepts it. */
export function cleanForSave(workflow: Workflow): Workflow {
  const trigger: Trigger = { ...workflow.trigger };
  if (trigger.type === "schedule") {
    if (trigger.every !== "week") delete trigger.weekday;
    if (trigger.every !== "month") delete trigger.day;
    if (trigger.every !== "hours") delete trigger.hours;
    if (trigger.every === "hours") delete trigger.at;
  } else {
    delete trigger.every;
    delete trigger.at;
    delete trigger.weekday;
    delete trigger.day;
    delete trigger.hours;
    delete trigger.timezone;
  }
  if (trigger.type !== "room_message") delete trigger.keyword;
  if (!["room_message", "meeting_ended"].includes(trigger.type) || !trigger.room) delete trigger.room;
  if (!["task_created", "task_blocked"].includes(trigger.type) || !trigger.team) delete trigger.team;
  const steps = workflow.steps.map((step) => {
    const out: Step = { ...step };
    for (const [key, value] of Object.entries(out)) {
      if (value === "" && key !== "text") delete out[key];
    }
    if (out.type === "ai_prompt" && !out.room) delete out.room;
    if (!out.label) delete out.label;
    return out;
  });
  return { name: workflow.name.trim(), description: workflow.description ?? "", trigger, steps };
}
