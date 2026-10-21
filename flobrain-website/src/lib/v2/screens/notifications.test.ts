import { describe, expect, it } from "vitest";

import { notificationsEmpty, unreadNotifications } from "./notifications";

describe("notifications logic", () => {
  it("keeps unread rows", () => {
    const rows = [
      { id: "1", kind: "room_message", read_at: null },
      { id: "2", kind: "room_message", read_at: "2026-01-01" },
    ];
    expect(unreadNotifications(rows)).toHaveLength(1);
    expect(notificationsEmpty([])).toBe(true);
  });
});
