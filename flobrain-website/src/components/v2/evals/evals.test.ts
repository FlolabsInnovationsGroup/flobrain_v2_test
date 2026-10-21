import { describe, expect, it } from "vitest";

import { EMPTY_DRAFT, checkCount, clampPercent, draftFrom, draftPayload, inFlight, lines, orderResults, regressions, score, type CaseResult } from "./evals";

function result(id: string, passed: boolean): CaseResult {
  return {
    case: id, name: id, input: id, expect: {}, answer: "", calls: [], checks: [], judge: null, passed,
    score: passed ? 1 : 0, error: "", sources: [], missing_sources: 0, tokens: 0, duration_ms: 0,
  };
}

describe("case drafts", () => {
  it("turns lines into unique phrases and round-trips a case", () => {
    expect(lines(" a \n\nb\na ")).toEqual(["a", "b"]);
    const draft = draftFrom({ input: "Q", must_include: ["x", "y"], max_words: 40, language: "ar", context_docs: [{ id: "d1", title: "NDA" }] });
    const out = draftPayload(draft);
    expect(out.ok && out.body).toMatchObject({ input: "Q", must_include: ["x", "y"], max_words: 40, language: "ar", context_doc_ids: ["d1"] });
  });

  it("refuses an empty question, a bad word limit and a tool both expected and forbidden", () => {
    expect(draftPayload(EMPTY_DRAFT)).toEqual({ ok: false, error: "input" });
    expect(draftPayload({ ...EMPTY_DRAFT, input: "Q", maxWords: "2.5" })).toEqual({ ok: false, error: "max_words" });
    expect(draftPayload({ ...EMPTY_DRAFT, input: "Q", maxWords: "0" })).toEqual({ ok: false, error: "max_words" });
    expect(draftPayload({ ...EMPTY_DRAFT, input: "Q", expectedTool: "email.draft", forbiddenTools: ["email.draft"] })).toEqual({ ok: false, error: "conflict" });
    const none = draftPayload({ ...EMPTY_DRAFT, input: "Q", expectedTool: "none", forbiddenTools: ["email.draft"] });
    expect(none.ok).toBe(true);
    const blank = draftPayload({ ...EMPTY_DRAFT, input: " Q ", maxWords: " " });
    expect(blank.ok && blank.body.max_words).toBeNull();
  });

  it("counts checks with the judge as one", () => {
    expect(checkCount({ must_include: ["a", "b"], must_not_include: [], must_cite: true, expected_tool: "none", forbidden_tools: ["x", "y"], max_words: null, language: "ar", rubric: "r" })).toBe(7);
  });
});

describe("runs", () => {
  it("formats scores and notices runs in flight", () => {
    expect(score(null)).toBe("–");
    expect(score(80)).toBe("80%");
    expect(score(62.25)).toBe("62.3%");
    expect(inFlight([{ status: "done" }, { status: "queued" }])).toBe(true);
    expect(inFlight([{ status: "done" }])).toBe(false);
  });

  it("lists new failures first, then old failures, then passes", () => {
    const detail = {
      results: [result("a", true), result("b", false), result("c", false), result("d", true)],
      previous_results: { b: { passed: false, score: 0 }, c: { passed: true, score: 1 } },
    };
    expect(regressions(detail)).toEqual(["c"]);
    expect(orderResults(detail).map((r) => r.case)).toEqual(["c", "b", "a", "d"]);
    expect(regressions({ results: detail.results })).toEqual([]);
  });

  it("clamps a pass mark", () => {
    expect(clampPercent("120", 80)).toBe(100);
    expect(clampPercent("-3", 80)).toBe(0);
    expect(clampPercent("", 80)).toBe(80);
    expect(clampPercent("abc", 80)).toBe(80);
  });
});
