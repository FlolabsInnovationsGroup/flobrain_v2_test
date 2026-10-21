import { describe, expect, it } from "vitest";

import { approvalLabel, formatClock, formatDuration, manualEntryProblem, mondayOf, share, shiftWeek, weekEnd } from "./time";

describe("time helpers", () => {
  it("shows durations as h:mm and the clock as HH:MM:SS", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(300)).toBe("0:05");
    expect(formatDuration(45000)).toBe("12:30");
    expect(formatDuration(-3600)).toBe("-1:00");
    expect(formatClock(3725)).toBe("01:02:05");
  });

  it("moves between weeks", () => {
    expect(mondayOf(new Date(2026, 9, 21))).toBe("2026-10-19");
    expect(mondayOf(new Date(2026, 9, 25))).toBe("2026-10-19");
    expect(shiftWeek("2026-10-19", -1)).toBe("2026-10-12");
    expect(weekEnd("2026-10-19")).toBe("2026-10-25");
  });

  it("checks manual entries", () => {
    const now = new Date("2026-10-21T12:00:00Z");
    expect(manualEntryProblem("", "", now)).toBe("Add a start and an end.");
    expect(manualEntryProblem("2026-10-21T10:00:00Z", "2026-10-21T09:00:00Z", now)).toBe("The end must be after the start.");
    expect(manualEntryProblem("2026-10-21T13:00:00Z", "2026-10-21T14:00:00Z", now)).toBe("You can't log time in the future.");
    expect(manualEntryProblem("2026-10-19T09:00:00Z", "2026-10-21T09:00:00Z", now)).toBe("One entry can be at most 24 hours.");
    expect(manualEntryProblem("2026-10-21T09:00:00Z", "2026-10-21T10:00:00Z", now)).toBeNull();
  });

  it("labels approval and bar shares", () => {
    expect(approvalLabel("submitted")).toBe("Waiting for approval");
    expect(approvalLabel("draft")).toBe("Not submitted");
    expect(share(1, 4)).toBe(25);
    expect(share(1, 0)).toBe(0);
  });
});
