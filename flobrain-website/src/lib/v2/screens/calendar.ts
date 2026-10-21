export type CalendarItem = {
  id: string;
  title: string;
  due_on: string;
  date?: string;
  kind?: string;
  status?: string;
  priority?: string;
  is_blocked?: boolean;
  overdue?: boolean;
  starts_at?: string;
  room?: string;
  room_name?: string;
  people?: Array<{ id: string; name: string }>;
};

export function groupCalendarByDate(items: CalendarItem[]): Record<string, CalendarItem[]> {
  return items.reduce<Record<string, CalendarItem[]>>((groups, item) => {
    const key = item.date ?? item.due_on;
    groups[key] = groups[key] ? [...groups[key], item] : [item];
    return groups;
  }, {});
}

/** The 7 dates (YYYY-MM-DD) of the week starting on ``monday``. */
export function weekDays(monday: string): string[] {
  const start = new Date(+monday.slice(0, 4), +monday.slice(5, 7) - 1, +monday.slice(8, 10));
  const pad = (n: number) => String(n).padStart(2, "0");
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  });
}

/** Overdue open tasks from before the window, so nothing late is hidden by paging forward. */
export function splitOverdue(items: CalendarItem[], from: string): { overdue: CalendarItem[]; rest: CalendarItem[] } {
  const overdue = items.filter((i) => i.kind === "task" && i.overdue && (i.date ?? i.due_on) < from);
  const rest = items.filter((i) => !overdue.includes(i));
  return { overdue, rest };
}
