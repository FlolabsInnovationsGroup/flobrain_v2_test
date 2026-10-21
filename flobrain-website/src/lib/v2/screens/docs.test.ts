import { describe, expect, it } from "vitest";

import { docsEmpty, isVersionConflict, nextDraft } from "./docs";

describe("docs logic", () => {
  it("detects empty and version conflicts", () => {
    const doc = { id: "1", title: "Spec", content_text: "v1", version: 2 };
    expect(docsEmpty([])).toBe(true);
    expect(isVersionConflict(2, 1)).toBe(true);
    expect(isVersionConflict(2, 2)).toBe(false);
    expect(nextDraft(doc, "v2")).toEqual({ version: 2, content_text: "v2" });
  });
});
