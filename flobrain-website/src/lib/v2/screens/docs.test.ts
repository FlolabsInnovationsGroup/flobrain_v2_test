import { describe, expect, it } from "vitest";

import {
  apiPath,
  applyMarkup,
  backupState,
  docsEmpty,
  formatBytes,
  isDirty,
  isVersionConflict,
  nextDraft,
  savePayload,
} from "./docs";

describe("docs logic", () => {
  const doc = { id: "1", title: "Spec", content_text: "v1", version: 2 };

  it("detects empty and version conflicts", () => {
    expect(docsEmpty([])).toBe(true);
    expect(isVersionConflict(2, 1)).toBe(true);
    expect(isVersionConflict(2, 2)).toBe(false);
    expect(nextDraft(doc, "v2")).toEqual({ version: 2, content_text: "v2" });
  });

  it("saves the base version and only a real title", () => {
    expect(savePayload(doc, "  ", "v2")).toEqual({ version: 2, content_text: "v2" });
    expect(savePayload(doc, "Spec", "v2")).toEqual({ version: 2, content_text: "v2" });
    expect(savePayload(doc, " New ", "v1")).toEqual({
      version: 2,
      content_text: "v1",
      title: "New",
    });
    expect(isDirty(doc, "Spec", "v1")).toBe(false);
    expect(isDirty(doc, "", "v1")).toBe(false);
    expect(isDirty(doc, "Spec", "v1 ")).toBe(true);
  });

  it("tells a restorable draft from a conflicting one", () => {
    expect(backupState(doc, null)).toBe("none");
    expect(backupState(doc, { version: 2, title: "Spec", text: "v1", at: "" })).toBe("none");
    expect(backupState(doc, { version: 2, title: "Spec", text: "mine", at: "" })).toBe("restore");
    expect(backupState(doc, { version: 1, title: "Spec", text: "mine", at: "" })).toBe("conflict");
  });

  it("applies toolbar markup", () => {
    expect(applyMarkup("hello world", 0, 5, "bold")).toEqual({
      text: "**hello** world",
      start: 2,
      end: 7,
    });
    expect(applyMarkup("a\nb", 0, 3, "list").text).toBe("- a\n- b");
    expect(applyMarkup("- a", 0, 3, "list").text).toBe("a");
    expect(applyMarkup("x", 1, 1, "heading").text).toBe("## x");
    const link = applyMarkup("see", 0, 3, "link");
    expect(link.text).toBe("[see](https://)");
    expect(link.text.slice(link.start, link.end)).toBe("https://");
  });

  it("formats sizes and API paths", () => {
    expect(formatBytes(13)).toBe("13 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(apiPath("/api/v2/orgs/x/files/y/upload")).toBe("/orgs/x/files/y/upload");
  });
});
