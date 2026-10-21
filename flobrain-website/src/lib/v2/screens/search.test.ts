import { describe, expect, it } from "vitest";

import { filterHits, searchEmpty } from "./search";

describe("search logic", () => {
  it("filters types and empty query results", () => {
    const rows = [
      { type: "room", id: "1", title: "Alpha" },
      { type: "doc", id: "2", title: "Spec" },
    ];
    expect(filterHits(rows, "doc")).toHaveLength(1);
    expect(filterHits(rows, "all")).toHaveLength(2);
    expect(searchEmpty("alpha", [])).toBe(true);
    expect(searchEmpty("", [])).toBe(false);
  });
});
