export type NotificationRow = {
  id: string;
  kind: string;
  payload?: Record<string, unknown>;
  read_at?: string | null;
};

export function unreadNotifications(rows: NotificationRow[]): NotificationRow[] {
  return rows.filter((row) => !row.read_at);
}

export function notificationsEmpty(rows: NotificationRow[]): boolean {
  return rows.length === 0;
}
