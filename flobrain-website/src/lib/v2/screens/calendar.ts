export type CalendarItem = { id: string; title: string; due_on: string; kind?: string };

export function groupCalendarByDate(items: CalendarItem[]): Record<string, CalendarItem[]> {
  return items.reduce<Record<string, CalendarItem[]>>((groups, item) => {
    const key = item.due_on;
    groups[key] = groups[key] ? [...groups[key], item] : [item];
    return groups;
  }, {});
}
