import { describe, expect, it } from "vitest";

import { DEFAULT_LAYOUT, effectiveLayout, pollEvery, roomFromHref, roomTabHref, type CockpitState } from "./layoutRules";

const custom: CockpitState = {
  mode: "custom",
  layout: { ...DEFAULT_LAYOUT, panels: { rooms: false, video: true, compact: false, right_rail: false }, accent: "#112233" },
  low_bandwidth: false,
};

describe("effectiveLayout", () => {
  it("uses the saved choices only in Custom, and only with the cockpit flag", () => {
    expect(effectiveLayout(custom).panels.video).toBe(true);
    expect(effectiveLayout(custom, false)).toEqual(DEFAULT_LAYOUT);
    expect(effectiveLayout({ ...custom, mode: "default" }).accent).toBe("#112233");
    expect(effectiveLayout({ ...custom, mode: "focus" }).panels.right_rail).toBe(false);
  });
  it("drops the video panel in low bandwidth", () => {
    expect(effectiveLayout({ ...custom, low_bandwidth: true }).panels.video).toBe(false);
  });
});

describe("room links and polling", () => {
  const id = "0b6f0b9e-1c2d-4e5f-8a9b-0c1d2e3f4a5b";
  it("opens the default tab", () => {
    expect(roomTabHref("demo", id, "docs")).toBe(`/w/demo/rooms/${id}/docs`);
    expect(roomTabHref("demo", id, "recordings")).toBe(`/w/demo/rooms/${id}/meetings`);
    expect(roomTabHref("demo", id, "tasks")).toBe(`/w/demo/tasks?room=${id}`);
    expect(roomTabHref("demo", id, "team")).toBe(`/w/demo/rooms/${id}`);
    expect(roomFromHref(`/w/demo/rooms/${id}`, "demo")).toBe(id);
    expect(roomFromHref(`/w/demo/rooms/${id}/docs`, "demo")).toBeNull();
  });
  it("polls slower on a slow connection", () => {
    expect(pollEvery(5000, false)).toBe(5000);
    expect(pollEvery(5000, true)).toBe(60000);
    expect(pollEvery(30000, true)).toBe(120000);
  });
});
