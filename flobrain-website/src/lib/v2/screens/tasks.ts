import type { Access } from "@/lib/v2/access";

import type { AssignActorRole } from "./assign";
import type { KanbanTask } from "./kanban";

export type TaskRow = KanbanTask & {
  description?: string;
  priority: string;
  position: number;
  due_on: string | null;
  completed_at?: string | null;
  team?: string | null;
  project?: string | null;
  room?: string | null;
  created_by?: string | null;
  assignees: string[];
  people: Array<{ id: string; name: string }>;
  can_edit?: boolean;
  can_delete?: boolean;
};

export const PRIORITIES = [
  { id: "low", label: "Low" },
  { id: "normal", label: "Normal" },
  { id: "high", label: "High" },
  { id: "urgent", label: "Urgent" },
] as const;

export function priorityLabel(priority: string | undefined): string {
  return PRIORITIES.find((p) => p.id === priority)?.label ?? "Normal";
}

export function priorityTone(priority: string | undefined): "neutral" | "waiting" | "bad" | "accent" {
  if (priority === "urgent") return "bad";
  if (priority === "high") return "waiting";
  if (priority === "low") return "neutral";
  return "accent";
}

/** Days from ``today`` (YYYY-MM-DD) to ``due`` (YYYY-MM-DD); negative when overdue. */
export function daysUntil(due: string, today: string): number {
  const a = Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10));
  const b = Date.UTC(+due.slice(0, 4), +due.slice(5, 7) - 1, +due.slice(8, 10));
  return Math.round((b - a) / 86400000);
}

export function localToday(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** A due date in plain words, plus whether it is late. Done tasks are never late. */
export function dueState(task: { due_on?: string | null; status: string }, today: string) {
  if (!task.due_on) return null;
  const days = daysUntil(task.due_on, today);
  const done = task.status === "done";
  if (!done && days < 0) return { text: "Overdue by {n} days", n: -days, late: true, soon: false };
  if (days === 0) return { text: "Due today", n: 0, late: false, soon: !done };
  if (days === 1) return { text: "Due tomorrow", n: 1, late: false, soon: !done };
  return { text: "Due {date}", n: days, late: false, soon: false };
}

export type BoardFilters = {
  view: "all" | "mine" | "assigned_by_me" | "completed";
  assignee: string;
  team: string;
  project: string;
  status: string;
  due: "" | "overdue" | "today" | "week" | "none";
  blocked: boolean;
  query: string;
};

export const EMPTY_FILTERS: BoardFilters = {
  view: "all",
  assignee: "",
  team: "",
  project: "",
  status: "",
  due: "",
  blocked: false,
  query: "",
};

/** Query parameters for ``GET /orgs/{org}/tasks`` (the text search stays on the client). */
export function taskQuery(filters: BoardFilters, room: string | null): Record<string, string> {
  const params: Record<string, string> = { page_size: "100" };
  if (filters.view !== "all") params.filter = filters.view;
  if (filters.assignee) params.assignee = filters.assignee;
  if (filters.team) params.team = filters.team;
  if (filters.project) params.project = filters.project;
  if (filters.status) params.status = filters.status;
  if (filters.due) params.due = filters.due;
  if (filters.blocked) params.blocked = "1";
  if (room) params.room = room;
  return params;
}

export function activeFilterCount(filters: BoardFilters): number {
  return (
    Number(filters.view !== "all") +
    Number(!!filters.assignee) +
    Number(!!filters.team) +
    Number(!!filters.project) +
    Number(!!filters.status) +
    Number(!!filters.due) +
    Number(filters.blocked)
  );
}

/** The person's role for assigning (Decision 2), from ``/me/access``. */
export function assignRole(access: Access | null): AssignActorRole {
  if (!access) return "member";
  if (access.is_platform_admin || access.org_role === "owner") return "owner";
  if (access.org_role === "admin") return "admin";
  if (access.leads_teams.length > 0) return "lead";
  return "member";
}

/** Leads assign within the teams they lead; admins anywhere; members only themselves. */
export function canAssignOthersOn(access: Access | null, team: string | null | undefined): boolean {
  const role = assignRole(access);
  if (role === "owner" || role === "admin") return true;
  if (role === "lead") return !!team && !!access?.leads_teams.includes(team);
  return false;
}

export type NewTask = {
  title: string;
  description: string;
  assignees: string[];
  due_on: string;
  priority: string;
  team: string;
  project: string;
};

/** What's wrong with the create form, in the words the spec uses, or null. */
export function newTaskProblem(form: NewTask, selfId: string | null): string | null {
  if (!form.title.trim()) return "Give the task a name.";
  if (form.title.trim().length > 200) return "Keep the name under 200 characters.";
  const others = form.assignees.filter((id) => id !== selfId);
  if (others.length && !form.due_on) return "Set a due date when you assign someone else.";
  return null;
}

export function newTaskBody(form: NewTask, room: string | null) {
  return {
    title: form.title.trim(),
    description: form.description.trim(),
    priority: form.priority || "normal",
    due_on: form.due_on || null,
    team: form.team || null,
    project: form.project || null,
    room: room || null,
    assignees: form.assignees.length ? form.assignees : undefined,
  };
}
