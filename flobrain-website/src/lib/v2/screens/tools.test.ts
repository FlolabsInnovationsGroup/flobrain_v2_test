import { describe, expect, it } from "vitest";

import { canCreateTool, isValidToolUrl, toolsEmpty } from "./tools";

describe("tools logic", () => {
  it("validates urls and empty rail", () => {
    expect(isValidToolUrl("https://figma.com")).toBe(true);
    expect(isValidToolUrl("notaurl")).toBe(false);
    expect(canCreateTool("Figma", "https://figma.com")).toBe(true);
    expect(canCreateTool(" ", "https://figma.com")).toBe(false);
    expect(toolsEmpty([])).toBe(true);
  });
});
