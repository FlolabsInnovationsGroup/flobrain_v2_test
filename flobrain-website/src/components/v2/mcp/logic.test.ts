import { describe, expect, it } from "vitest";

import { argsLine, callQuery, draftFrom, duration, EMPTY_FILTERS, fromDateInput, isPast, policyBody, toDateInput, toggle, toolUsable } from "./logic";
import type { Policy } from "./types";

const policy: Policy = {
  tool_rules: { echo: "deny" },
  read_only: true,
  expires_at: null,
  expired: false,
  buddy_ids: ["b1"],
  updated_at: null,
  tools: [
    { name: "partner_status", description: "", read_only: true, rule: "allow", usable: true },
    { name: "echo", description: "", read_only: true, rule: "deny", usable: false },
    { name: "delete_order", description: "", read_only: false, rule: "allow", usable: false },
  ],
};

describe("MCP hub helpers", () => {
  it("sends only the filters that are set", () => {
    expect(callQuery(EMPTY_FILTERS)).toEqual({ days: "30" });
    expect(callQuery({ ...EMPTY_FILTERS, ok: "false", tool: "echo" })).toEqual({ days: "30", ok: "false", tool: "echo" });
  });

  it("shows the redacted shape in one line", () => {
    expect(argsLine({ title: "text (5 chars)", api_key: "[hidden]", nested: { a: "number" } })).toBe("title: text (5 chars), api_key: [hidden], nested: {a: number}");
    expect(argsLine({})).toBe("");
  });

  it("formats durations", () => {
    expect(duration(420)).toBe("420 ms");
    expect(duration(1500)).toBe("1.5 s");
    expect(duration(12000)).toBe("12 s");
  });

  it("round-trips the end date through the date input", () => {
    const iso = fromDateInput("2027-01-31");
    expect(iso).not.toBeNull();
    expect(toDateInput(iso)).toBe("2027-01-31");
    expect(fromDateInput("")).toBeNull();
    expect(fromDateInput("31/01/2027")).toBeNull();
    expect(isPast("2000-01-01")).toBe(true);
    expect(isPast("")).toBe(false);
  });

  it("builds the policy draft and body, and predicts which tools stay usable", () => {
    const draft = draftFrom(policy);
    expect(draft.rules).toEqual({ partner_status: "allow", echo: "deny", delete_order: "allow" });
    expect(toolUsable(draft, policy.tools[0], false)).toBe(true);
    expect(toolUsable(draft, policy.tools[1], false)).toBe(false);
    expect(toolUsable(draft, policy.tools[2], false)).toBe(false);
    expect(toolUsable({ ...draft, readOnly: false }, policy.tools[2], false)).toBe(true);
    expect(toolUsable(draft, policy.tools[0], true)).toBe(false);
    expect(policyBody(draft)).toEqual({ tool_rules: draft.rules, read_only: true, expires_at: null, buddy_ids: ["b1"] });
  });

  it("toggles ids", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
  });
});
