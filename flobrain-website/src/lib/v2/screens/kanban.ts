export const KANBAN_COLUMNS = [
  { id: "to_do", label: "To Do" },
  { id: "in_progress", label: "In Progress" },
  { id: "done", label: "Done" },
] as const;

export type KanbanTask = {
  id: string;
  title: string;
  status: string;
  assignees?: string[];
};

export type KanbanFilters = {
  query?: string;
  assignee?: string;
  status?: string;
};

export function filterKanbanTasks(tasks: KanbanTask[], filters: KanbanFilters = {}): KanbanTask[] {
  return tasks.filter((task) => {
    if (filters.status && task.status !== filters.status) return false;
    if (filters.assignee && !(task.assignees ?? []).includes(filters.assignee)) return false;
    if (filters.query && !task.title.toLowerCase().includes(filters.query.trim().toLowerCase())) {
      return false;
    }
    return true;
  });
}

export function groupKanbanTasks(tasks: KanbanTask[], filters: KanbanFilters = {}) {
  const filtered = filterKanbanTasks(tasks, filters);
  return Object.fromEntries(
    KANBAN_COLUMNS.map((column) => [column.id, filtered.filter((task) => task.status === column.id)]),
  ) as Record<(typeof KANBAN_COLUMNS)[number]["id"], KanbanTask[]>;
}

export function nextKanbanStatuses(status: string) {
  return KANBAN_COLUMNS.filter((column) => column.id !== status);
}
