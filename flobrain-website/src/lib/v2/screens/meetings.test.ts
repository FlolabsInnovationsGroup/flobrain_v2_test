import { describe, expect, it } from "vitest";

import { canShowJoinUrl, meetingsEmpty, needsConfirm, sortRecordings } from "./meetings";

describe("meetings logic", () => {
  it("sorts recordings and requires confirm", () => {
    const rows = [
      { id: "1", play_url: "/a", recorded_at: "2026-01-01T00:00:00Z", meeting: "m" },
      { id: "2", play_url: "/b", recorded_at: "2026-02-01T00:00:00Z", meeting: "m" },
    ];
    expect(sortRecordings(rows, true)[0].id).toBe("2");
    expect(sortRecordings(rows, false)[0].id).toBe("1");
    expect(meetingsEmpty([], [])).toBe(true);
    expect(needsConfirm(false)).toBe(true);
    expect(needsConfirm(true)).toBe(false);
    expect(canShowJoinUrl("https://meet.local/abc")).toBe(false);
    expect(canShowJoinUrl(null)).toBe(false);
    expect(canShowJoinUrl("https://zoom.example/j/1")).toBe(true);
  });
});
