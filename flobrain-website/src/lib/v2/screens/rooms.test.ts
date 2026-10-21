import { describe, expect, it } from "vitest";

import { filterRooms, roomsEmpty, unreadLabel } from "./rooms";

const rooms = [
  { id: "1", name: "Alpha", kind: "team", unread: 3 },
  { id: "2", name: "Beta", kind: "direct", unread: 0 },
];

describe("rooms logic", () => {
  it("filters and labels unread", () => {
    expect(filterRooms(rooms, "alp")).toHaveLength(1);
    expect(filterRooms(rooms, "direct")[0].id).toBe("2");
    expect(unreadLabel(3)).toBe("3");
    expect(unreadLabel(120)).toBe("99+");
    expect(unreadLabel(0)).toBeNull();
    expect(roomsEmpty([])).toBe(true);
    expect(roomsEmpty(rooms)).toBe(false);
  });
});
