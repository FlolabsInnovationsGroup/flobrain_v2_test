import { describe, expect, it } from "vitest";

import { acceptedFile, countLines, defaultChoice, defaultMapping, errorParts, formatBytes, isActive, mappingToSend, percent, selectedMessages, statusTone } from "./logic";
import type { SlackChannel } from "./types";

const channel = (over: Partial<SlackChannel>): SlackChannel => ({
  id: "C1",
  name: "general",
  kind: "public",
  archived: false,
  messages: 10,
  threads: 0,
  first: "2026-09-01T00:00:00Z",
  last: "2026-09-02T00:00:00Z",
  members: 3,
  matched: 2,
  suggested_team: "",
  ...over,
});
const teams = [
  { id: "t-eng", name: "Engineering" },
  { id: "t-des", name: "Design" },
];

describe("imports logic", () => {
  it("accepts the right files per source", () => {
    expect(acceptedFile("slack", "export.ZIP")).toBe(true);
    expect(acceptedFile("slack", "export.tar")).toBe(false);
    expect(acceptedFile("files", "Handbook.docx")).toBe(true);
    expect(acceptedFile("files", "photo.jpg")).toBe(false);
    expect(acceptedFile("notion_zip", "notes.md")).toBe(false);
  });

  it("guesses a destination per channel", () => {
    expect(defaultChoice(channel({ name: "engineering" }), teams)).toEqual({ target: "team", team_id: "t-eng" });
    expect(defaultChoice(channel({ name: "random", suggested_team: "t-des" }), teams)).toEqual({ target: "team", team_id: "t-des" });
    expect(defaultChoice(channel({ name: "random" }), teams)).toEqual({ target: "new_team" });
    expect(defaultChoice(channel({ name: "old", archived: true }), teams)).toEqual({ target: "skip" });
    expect(defaultChoice(channel({ kind: "private", matched: 1 }), teams)).toEqual({ target: "private" });
    expect(defaultChoice(channel({ kind: "dm", matched: 0 }), teams)).toEqual({ target: "skip" });
  });

  it("sends only what is chosen and opted in", () => {
    const channels = [
      channel({ id: "C1", name: "engineering", messages: 60 }),
      channel({ id: "G1", name: "secret", kind: "private", messages: 20 }),
      channel({ id: "D1", name: "dm", kind: "dm", messages: 5 }),
      channel({ id: "C2", name: "old", archived: true, messages: 7 }),
    ];
    const mapping = defaultMapping({ channels, has_private: true, has_dms: true }, teams);
    expect(mapping.include_private).toBe(true);
    expect(mapping.include_dms).toBe(false);
    const sent = mappingToSend(mapping, channels);
    expect(Object.keys(sent.channels).sort()).toEqual(["C1", "G1"]);
    expect(selectedMessages(mapping, channels)).toBe(80);
    expect(Object.keys(mappingToSend({ ...mapping, include_private: false }, channels).channels)).toEqual(["C1"]);
    expect(mappingToSend({ ...mapping, channels: { C1: { target: "team" } } }, channels).channels).toEqual({});
  });

  it("formats progress, sizes, tones and errors", () => {
    expect(percent({ status: "running", progress: { done: 50, total: 200 } })).toBe(25);
    expect(percent({ status: "running", progress: {} })).toBeNull();
    expect(percent({ status: "done", progress: {} })).toBe(100);
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(statusTone("done")).toBe("good");
    expect(statusTone("failed")).toBe("bad");
    expect(statusTone("running")).toBe("accent");
    expect(isActive({ status: "undoing" })).toBe(true);
    expect(isActive(null)).toBe(false);
    expect(errorParts("traversal: The archive has a file with an unsafe name")).toEqual({ code: "traversal", text: "The archive has a file with an unsafe name" });
    expect(countLines({ messages: 3, documents: 0, teams_created: 1 })).toEqual([
      { template: "{n} messages", n: 3 },
      { template: "{n} new teams", n: 1 },
    ]);
  });
});
