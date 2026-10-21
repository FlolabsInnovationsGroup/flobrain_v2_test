import { describe, expect, it } from "vitest";

import { addStep, cleanForSave, MAX_STEPS, moveStep, removeStep, stepIssues, triggerIssues, type Step } from "./steps";

const three: Step[] = [
  { type: "ai_prompt", prompt: "Summarise", context: "blocked_tasks" },
  { type: "notify", roles: ["owner"], text: "Got: {{steps.1.output}}" },
  { type: "post_to_room", room: "r1", text: "{{steps.1.output}} and {{ steps.2.output }}" },
];

describe("step list editor", () => {
  it("adds a step that reuses the previous answer, up to the limit", () => {
    const added = addStep(three, "send_email");
    expect(added).toHaveLength(4);
    expect(added[3]).toMatchObject({ type: "send_email", body: "{{steps.3.output}}" });
    expect(addStep([], "post_to_room")[0]).toMatchObject({ text: "" });
    let full: Step[] = [];
    for (let i = 0; i < MAX_STEPS + 3; i++) full = addStep(full, "daily_brief");
    expect(full).toHaveLength(MAX_STEPS);
  });

  it("moves a step and keeps references on the same steps", () => {
    const moved = moveStep(three, 0, 1); // the AI step becomes step 2
    expect(moved.map((s) => s.type)).toEqual(["notify", "ai_prompt", "post_to_room"]);
    expect(moved[0].text).toBe("Got: {{steps.2.output}}");
    expect(moved[2].text).toBe("{{steps.2.output}} and {{steps.1.output}}");
    expect(moveStep(three, 0, 9)).toBe(three);
    expect(moveStep(three, 1, 1)).toBe(three);
  });

  it("removes a step and renumbers or drops references", () => {
    const removed = removeStep(three, 0);
    expect(removed).toHaveLength(2);
    expect(removed[0].text).toBe("Got: ");
    expect(removed[1].text).toBe(" and {{steps.1.output}}");
    expect(removeStep(three, 7)).toBe(three);
  });

  it("flags forward references and missing fields", () => {
    const issues = stepIssues(moveStep(three, 0, 2), { type: "manual" });
    expect(issues[0]).toContain("Uses the answer of a step that doesn't come before it.");
    expect(stepIssues([{ type: "post_to_room", room: "trigger", text: "x" }], { type: "schedule", every: "day", at: "09:00" })[0]).toHaveLength(1);
    expect(stepIssues([{ type: "post_to_room", room: "trigger", text: "x" }], { type: "meeting_ended" })[0]).toBeUndefined();
    expect(stepIssues([{ type: "notify", roles: [], text: "x" }], { type: "manual" })[0]).toEqual(["Pick who to notify."]);
    expect(stepIssues([{ type: "call_webhook", url: "http://x" }], { type: "manual" })[0]).toEqual(["Use an https address."]);
    expect(triggerIssues({ type: "schedule", every: "day", at: "9" })).toEqual(["Use a time like 09:00."]);
    expect(triggerIssues({ type: "schedule", every: "hours", hours: 4 })).toEqual([]);
  });

  it("cleans the body for the strict server schema", () => {
    const body = cleanForSave({
      name: "  Digest ",
      trigger: { type: "schedule", every: "week", at: "09:00", weekday: 0, day: 3, hours: 2, keyword: "x" },
      steps: [{ type: "ai_prompt", prompt: "x", room: "", label: "" }],
    });
    expect(body.name).toBe("Digest");
    expect(body.trigger).toEqual({ type: "schedule", every: "week", at: "09:00", weekday: 0 });
    expect(body.steps[0]).toEqual({ type: "ai_prompt", prompt: "x" });
    expect(cleanForSave({ name: "x", trigger: { type: "task_blocked", every: "day", room: "r" }, steps: [] }).trigger).toEqual({ type: "task_blocked" });
  });
});
