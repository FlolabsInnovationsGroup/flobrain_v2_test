import { describe, expect, it } from "vitest";

import { acceptedFile } from "./AddSource";
import { scheduleText } from "./ReportsPanel";

const tr = (text: string, vars?: Record<string, string | number>) => text.replace(/\{(\w+)\}/g, (_, k: string) => String(vars?.[k] ?? ""));

describe("data helpers", () => {
  it("accepts only spreadsheet files", () => {
    expect(acceptedFile("signups.CSV")).toBe(true);
    expect(acceptedFile("book.xlsx")).toBe(true);
    expect(acceptedFile("evil.exe")).toBe(false);
    expect(acceptedFile("book.xls")).toBe(false);
  });

  it("words report schedules", () => {
    expect(scheduleText({ cadence: "weekly", weekday: 0, day_of_month: 1, hour: 7 }, tr)).toBe("Weekly on Monday at 07:00 UTC");
    expect(scheduleText({ cadence: "monthly", weekday: 0, day_of_month: 15, hour: 18 }, tr)).toBe("Monthly on day 15 at 18:00 UTC");
  });
});
