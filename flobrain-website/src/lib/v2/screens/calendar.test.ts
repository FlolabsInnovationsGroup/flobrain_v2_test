import { describe, expect, it } from "vitest";

import { groupCalendarByDate } from "./calendar";

describe("calendar logic", () => {
  it("groups items by due date", () => {
    const grouped = groupCalendarByDate([
      { id: "1", title: "A", due_on: "2026-10-20" },
      { id: "2", title: "B", due_on: "2026-10-20" },
      { id: "3", title: "C", due_on: "2026-10-21" },
    ]);
    expect(grouped["2026-10-20"]).toHaveLength(2);
    expect(grouped["2026-10-21"][0].id).toBe("3");
  });
});
