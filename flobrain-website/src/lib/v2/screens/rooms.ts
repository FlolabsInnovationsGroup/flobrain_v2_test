export type RoomRow = {
  id: string;
  name: string;
  kind: string;
  unread?: number;
};

export function filterRooms(rooms: RoomRow[], query: string): RoomRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rooms;
  return rooms.filter((room) => room.name.toLowerCase().includes(q) || room.kind.toLowerCase().includes(q));
}

export function roomsEmpty(rooms: RoomRow[]): boolean {
  return rooms.length === 0;
}

export function unreadLabel(unread?: number): string | null {
  if (!unread || unread < 1) return null;
  return unread > 99 ? "99+" : String(unread);
}
