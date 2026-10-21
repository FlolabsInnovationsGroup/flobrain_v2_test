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

import { splitOverdue, weekDays } from "./calendar";

describe("calendar windows", () => {
  it("lists a week's days and pulls out late tasks", () => {
    expect(weekDays("2026-10-26")).toEqual(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]);
    const { overdue, rest } = splitOverdue(
      [
        { id: "1", title: "Late", due_on: "2026-10-01", kind: "task", overdue: true },
        { id: "2", title: "Meeting", due_on: "2026-10-01", kind: "meeting" },
        { id: "3", title: "Soon", due_on: "2026-10-30", kind: "task", overdue: false },
      ],
      "2026-10-21",
    );
    expect(overdue.map((i) => i.id)).toEqual(["1"]);
    expect(rest.map((i) => i.id)).toEqual(["2", "3"]);
  });

  it("groups by date when the server sends one", () => {
    expect(Object.keys(groupCalendarByDate([{ id: "m", title: "M", due_on: "2026-10-20", date: "2026-10-21" }]))).toEqual(["2026-10-21"]);
  });
});
