import { describe, expect, it } from "vitest";

import { isEmptyList, screenStateFromHttp } from "./status";

describe("screenStateFromHttp", () => {
  it("maps access and empty states", () => {
    expect(screenStateFromHttp(403)).toBe("no-access");
    expect(screenStateFromHttp(404)).toBe("no-access");
    expect(screenStateFromHttp(500)).toBe("error");
    expect(screenStateFromHttp(200, true)).toBe("empty");
    expect(screenStateFromHttp(200, false)).toBe("ready");
  });

  it("treats paginated empty lists as empty", () => {
    expect(isEmptyList({ results: [] })).toBe(true);
    expect(isEmptyList({ results: [{ id: "1" }] })).toBe(false);
  });
});
