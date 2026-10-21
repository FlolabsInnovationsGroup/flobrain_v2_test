export const KANBAN_COLUMNS = [
  { id: "to_do", label: "To Do" },
  { id: "in_progress", label: "In Progress" },
  { id: "done", label: "Done" },
] as const;

export type KanbanStatus = (typeof KANBAN_COLUMNS)[number]["id"];

export type KanbanTask = {
  id: string;
  title: string;
  status: string;
  assignees?: string[];
  position?: number;
  priority?: string;
  due_on?: string | null;
  is_blocked?: boolean;
  blocked_reason?: string;
  blocked_since?: string | null;
  people?: Array<{ id: string; name: string }>;
  can_edit?: boolean;
};

export type KanbanFilters = {
  query?: string;
  assignee?: string;
  status?: string;
};

export function filterKanbanTasks<T extends KanbanTask>(tasks: T[], filters: KanbanFilters = {}): T[] {
  return tasks.filter((task) => {
    if (filters.status && task.status !== filters.status) return false;
    if (filters.assignee && !(task.assignees ?? []).includes(filters.assignee)) return false;
    if (filters.query && !task.title.toLowerCase().includes(filters.query.trim().toLowerCase())) {
      return false;
    }
    return true;
  });
}

function byPosition(a: KanbanTask, b: KanbanTask) {
  return (a.position ?? 0) - (b.position ?? 0);
}

export function groupKanbanTasks<T extends KanbanTask>(tasks: T[], filters: KanbanFilters = {}) {
  const filtered = filterKanbanTasks(tasks, filters);
  return Object.fromEntries(
    KANBAN_COLUMNS.map((column) => [column.id, filtered.filter((task) => task.status === column.id).sort(byPosition)]),
  ) as Record<KanbanStatus, T[]>;
}

export function nextKanbanStatuses(status: string) {
  return KANBAN_COLUMNS.filter((column) => column.id !== status);
}

/** The column to the start or end side of ``status`` (keyboard moves), or null at the edge. */
export function neighbourColumn(status: string, step: -1 | 1): KanbanStatus | null {
  const index = KANBAN_COLUMNS.findIndex((column) => column.id === status);
  const next = KANBAN_COLUMNS[index + step];
  return index < 0 || !next ? null : next.id;
}

/**
 * Optimistic move: put ``id`` into ``status`` before the task ``beforeId`` (or at the end) and
 * renumber positions in the columns it touched, the same way the server does.
 */
export function moveTask<T extends KanbanTask>(tasks: T[], id: string, status: string, beforeId: string | null): T[] {
  const moving = tasks.find((task) => task.id === id);
  if (!moving) return tasks;
  const column = tasks.filter((task) => task.status === status && task.id !== id).sort(byPosition);
  let index = beforeId ? column.findIndex((task) => task.id === beforeId) : column.length;
  if (index < 0) index = column.length;
  column.splice(index, 0, { ...moving, status });
  const positions = new Map(column.map((task, i) => [task.id, i]));
  const source = moving.status !== status ? tasks.filter((t) => t.status === moving.status && t.id !== id).sort(byPosition) : [];
  source.forEach((task, i) => positions.set(task.id, i));
  return tasks.map((task) => {
    if (task.id === id) return { ...task, status, position: positions.get(id) ?? 0 };
    return positions.has(task.id) ? { ...task, position: positions.get(task.id) } : task;
  });
}

/** For the "move up/down" buttons: the id to place before so the task moves one step. */
export function beforeForStep(column: KanbanTask[], id: string, step: -1 | 1): string | null | undefined {
  const index = column.findIndex((task) => task.id === id);
  if (index < 0) return undefined;
  if (step === -1) return index === 0 ? undefined : column[index - 1].id;
  if (index >= column.length - 1) return undefined;
  return column[index + 2]?.id ?? null;
}
