import { describe, expect, it } from "vitest";

import {
  canSendMessage,
  displayBody,
  formatRoomTimestamp,
  loadCursorPages,
  mergeMessages,
  nextCursorFromUrl,
  shouldPoll,
} from "./chat";

describe("chat logic", () => {
  it("merges, formats timestamps, and gates send/poll", () => {
    const older = { id: "1", body: "hi", created_at: "2026-01-01T00:00:00Z" };
    const newer = { id: "2", body: "there", created_at: "2026-01-01T00:01:00Z", translation: "[ar] there", translated: true };
    expect(mergeMessages([newer], [older]).map((row) => row.id)).toEqual(["1", "2"]);
    expect(displayBody(newer, true)).toBe("[ar] there");
    expect(displayBody(newer, false)).toBe("there");
    expect(canSendMessage("  ")).toBe(false);
    expect(canSendMessage("ok")).toBe(true);
    expect(shouldPoll(true, false)).toBe(true);
    expect(shouldPoll(true, true)).toBe(false);
    const now = Date.parse("2026-01-01T00:10:00Z");
    expect(formatRoomTimestamp("2026-01-01T00:09:50Z", now)).toBe("just now");
    expect(formatRoomTimestamp("2026-01-01T00:05:00Z", now)).toBe("5 min ago");
    expect(formatRoomTimestamp("2026-01-01T00:00:00Z", now)).toBe("10 min ago");
  });

  it("uses hours and locale for older stamps", () => {
    const now = Date.parse("2026-01-02T12:00:00Z");
    expect(formatRoomTimestamp("2026-01-02T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatRoomTimestamp("2025-12-01T12:00:00Z", now).length).toBeGreaterThan(4);
  });

  it("follows cursor next links", async () => {
    expect(nextCursorFromUrl("http://127.0.0.1/api/v2/orgs/1/rooms/2/messages?cursor=abc")).toBe("abc");
    expect(nextCursorFromUrl(null)).toBeNull();
    const pages = [
      { results: [{ id: "2", body: "newer", created_at: "2026-01-01T00:01:00Z" }], next: "?cursor=older" },
      { results: [{ id: "1", body: "older", created_at: "2026-01-01T00:00:00Z" }], next: null },
    ];
    let calls = 0;
    const loaded = await loadCursorPages(async () => pages[calls++]);
    expect(loaded.map((row) => row.id)).toEqual(["1", "2"]);
  });
});
