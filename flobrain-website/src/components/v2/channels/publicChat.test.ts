import { describe, expect, it } from "vitest";

import { mergeMessages, parentOrigin, type PublicMessage } from "./publicChat";

const msg = (id: string, at: string): PublicMessage => ({ id, role: "customer", text: id, created_at: at, citations: [] });

type Win = Parameters<typeof parentOrigin>[0];
const win = (framed: boolean, ancestors: string[] = [], referrer = ""): Win => {
  const top = {};
  return {
    self: framed ? ({} as Window) : (top as Window),
    top: top as Window,
    location: { ancestorOrigins: ancestors.length ? Object.assign([...ancestors], { contains: () => false, item: (i: number) => ancestors[i] }) : undefined } as unknown as Win["location"],
    document: { referrer } as Document,
  } as Win;
};

describe("website chat helpers", () => {
  it("trusts the browser's parent origin over the claimed one", () => {
    expect(parentOrigin(win(false), "https://claimed.example")).toBe("");
    expect(parentOrigin(win(true, ["https://shop.example"]), "https://claimed.example")).toBe("https://shop.example");
    expect(parentOrigin(win(true, [], "https://ref.example/page?x=1"), "https://claimed.example")).toBe("https://ref.example");
    expect(parentOrigin(win(true), "https://claimed.example")).toBe("https://claimed.example");
  });

  it("merges messages by id in time order", () => {
    const merged = mergeMessages([msg("a", "2026-01-01T00:00:01Z")], [msg("b", "2026-01-01T00:00:00Z"), msg("a", "2026-01-01T00:00:01Z")]);
    expect(merged.map((m) => m.id)).toEqual(["b", "a"]);
  });
});
