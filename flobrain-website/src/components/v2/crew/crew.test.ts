import { describe, expect, it } from "vitest";

import { activeFirst, compact, duration, feedbackBody, money, nextRating, percent, reasonLabel, type QualityRow } from "./crew";

function row(name: string, answers = 0): QualityRow {
  return {
    id: name, slug: name, name, icon: "", builtin: true, answers, ratings: 0, helpful: 0, not_helpful: 0, helpful_rate: null,
    approvals: { proposed: 0, approved: 0, rejected: 0, waiting: 0 }, median_latency_ms: null, measured: 0,
    with_sources_rate: null, tokens: 0, cost: "0.0000", unpriced_calls: 0, routed: 0, routing_share: null, top_reasons: [],
  };
}

describe("buddy feedback", () => {
  it("toggles a rating off when clicked again", () => {
    expect(nextRating(null, "up")).toBe("up");
    expect(nextRating("up", "up")).toBeNull();
    expect(nextRating("up", "down")).toBe("down");
  });

  it("sends a reason and note only with not helpful", () => {
    expect(feedbackBody(7, "up", "wrong", "note")).toEqual({ message: 7, rating: "up" });
    expect(feedbackBody(7, "down", "wrong", "  late  ")).toEqual({ message: 7, rating: "down", reason: "wrong", note: "late" });
    expect(feedbackBody(7, "down", "", "", "b1")).toEqual({ message: 7, rating: "down", buddy: "b1" });
    expect((feedbackBody(7, "down", "", "x".repeat(400)).note as string).length).toBe(300);
  });

  it("labels reasons and keeps unknown codes readable", () => {
    expect(reasonLabel("no_sources")).toBe("No sources");
    expect(reasonLabel("weird")).toBe("weird");
  });
});

describe("quality formatting", () => {
  it("shows a dash for missing data, not zero", () => {
    expect(percent(null)).toBe("–");
    expect(percent(0)).toBe("0%");
    expect(percent(0.8666)).toBe("87%");
    expect(duration(null)).toBe("–");
    expect(duration(840)).toBe("840 ms");
    expect(duration(1534)).toBe("1.5 s");
  });

  it("formats counts and money", () => {
    expect(compact(950)).toBe("950");
    expect(compact(1500)).toBe("1.5k");
    expect(compact(12_400)).toBe("12k");
    expect(compact(1_500_000)).toBe("1.5M");
    expect(money("0.0000")).toBe("$0");
    expect(money("0.0040")).toBe("<$0.01");
    expect(money("2.5")).toBe("$2.50");
  });

  it("puts buddies with activity first and keeps their order", () => {
    const sorted = activeFirst([row("idle"), row("busy", 3), row("also", 1)]);
    expect(sorted.map((r) => r.name)).toEqual(["busy", "also", "idle"]);
  });
});
