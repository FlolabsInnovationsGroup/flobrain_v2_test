import { describe as group, expect, it } from "vitest";

import { describe, describeText, notificationsEmpty, unreadNotifications } from "./notifications";

group("notifications logic", () => {
  it("keeps unread rows", () => {
    const rows = [
      { id: "1", kind: "room_message", read_at: null },
      { id: "2", kind: "room_message", read_at: "2026-01-01" },
    ];
    expect(unreadNotifications(rows)).toHaveLength(1);
    expect(notificationsEmpty([])).toBe(true);
  });

  it("names the event and links inside the workspace only", () => {
    expect(describeText({ id: "1", kind: "task.assigned", payload: { title: "Ship" } })).toBe("You were assigned “Ship”");
    expect(describe({ id: "1", kind: "task.assigned", payload: { title: "Ship" } }).link).toBe("tasks");
    expect(describe({ id: "2", kind: "x", payload: { text: "Hi", link: "https://evil.test" } }).link).toBeNull();
    expect(describe({ id: "3", kind: "x", payload: { link: "//evil.test" } }).link).toBeNull();
    expect(describeText({ id: "4", kind: "billing.notice", payload: {} })).toBe("billing notice");
  });
});
