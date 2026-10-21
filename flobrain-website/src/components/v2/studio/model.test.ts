import { describe, expect, it } from "vitest";

import {
  addCut,
  addKeep,
  keptMask,
  keptSeconds,
  monthGrid,
  moveKeep,
  parseRows,
  removedMask,
  removeFillers,
  restoreRange,
  setSingle,
  wordAt,
  type Op,
  type Word,
} from "./model";

const words: Word[] = [
  { w: "So,", start: 0, end: 0.3 },
  { w: "um,", start: 0.4, end: 0.6 },
  { w: "we", start: 0.7, end: 0.9 },
  { w: "launch", start: 1.0, end: 1.4 },
  { w: "soon.", start: 1.5, end: 1.9 },
];

describe("studio EDL helpers", () => {
  it("cuts and restores word ranges, merging touching cuts", () => {
    let ops: Op[] = addCut([], "a", words, 1, 1);
    expect(removedMask(words, ops, "a")).toEqual([false, true, false, false, false]);
    ops = addCut(ops, "a", words, 2, 1); // reversed selection, overlaps the first cut
    expect(ops.filter((o) => o.op === "cut")).toHaveLength(1);
    expect(ops[0]).toMatchObject({ start: 0.4, end: 0.9, by: "user" });
    expect(removedMask(words, restoreRange(ops, "a", words, 2, 2), "a").some(Boolean)).toBe(false);
    expect(removedMask(words, ops, "other").some(Boolean)).toBe(false);
  });

  it("removes filler words once", () => {
    const first = removeFillers([], "a", words);
    expect(first.count).toBe(1);
    expect(removeFillers(first.ops, "a", words).count).toBe(0);
  });

  it("keeps segments in order and reorders them", () => {
    let ops: Op[] = [{ op: "captions", language: "en", burn_in: true }];
    ops = addKeep(ops, "a", words, 3, 4);
    ops = addKeep(ops, "a", words, 0, 1);
    expect(keptMask(words, ops, "a")).toEqual([true, true, false, true, true]);
    const moved = moveKeep(ops, 1, -1);
    expect(moved[0].op).toBe("captions");
    expect(moved.filter((o) => o.op === "keep").map((o) => (o as { start: number }).start)).toEqual([0, 1]);
    expect(moveKeep(ops, 0, -1)).toBe(ops);
    expect(keptSeconds(ops, "a", 10)).toBeCloseTo(0.9 + 0.6);
    expect(keptSeconds(addCut([], "a", words, 3, 3), "a", 10)).toBeCloseTo(9.6);
  });

  it("replaces single operations", () => {
    const ops = setSingle([{ op: "reframe", aspect: "16:9" }], "reframe", { op: "reframe", aspect: "9:16", mode: "auto" });
    expect(ops).toEqual([{ op: "reframe", aspect: "9:16", mode: "auto" }]);
    expect(setSingle(ops, "reframe", null)).toEqual([]);
  });

  it("finds the playing word and builds a month grid", () => {
    expect(wordAt(words, 1.2)).toBe(3);
    expect(wordAt(words, 0.35)).toBe(-1);
    const grid = monthGrid(2026, 9); // October 2026 starts on a Thursday
    expect(grid).toHaveLength(42);
    expect(grid[0].getDay()).toBe(1);
    expect(grid[3].getDate()).toBe(1);
  });

  it("parses batch rows", () => {
    expect(parseRows("What next?\n\n Why? ", ["question"])).toEqual([{ question: "What next?" }, { question: "Why?" }]);
    expect(parseRows("A | B\nC", ["title", "subtitle"])).toEqual([{ title: "A", subtitle: "B" }, { title: "C" }]);
  });
});
