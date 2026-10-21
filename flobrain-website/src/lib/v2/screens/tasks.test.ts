import { describe, expect, it } from "vitest";

import type { Access } from "@/lib/v2/access";

import {
  activeFilterCount,
  assignRole,
  canAssignOthersOn,
  daysUntil,
  dueState,
  EMPTY_FILTERS,
  newTaskBody,
  newTaskProblem,
  priorityTone,
  taskQuery,
} from "./tasks";

const access = (over: Partial<Access>): Access => ({
  org: { id: "o", slug: "o", name: "O", demo: false },
  user_id: "me",
  org_role: "member",
  is_platform_admin: false,
  leads_teams: [],
  permissions: [],
  flags: {},
  demo_role: null,
  ...over,
});

describe("task helpers", () => {
  it("words due dates", () => {
    expect(daysUntil("2026-10-22", "2026-10-21")).toBe(1);
    expect(dueState({ due_on: "2026-10-19", status: "to_do" }, "2026-10-21")).toMatchObject({ text: "Overdue by {n} days", n: 2, late: true });
    expect(dueState({ due_on: "2026-10-19", status: "done" }, "2026-10-21")?.late).toBe(false);
    expect(dueState({ due_on: "2026-10-22", status: "to_do" }, "2026-10-21")?.text).toBe("Due tomorrow");
    expect(dueState({ due_on: null, status: "to_do" }, "2026-10-21")).toBeNull();
  });

  it("builds the list query from filters and the room", () => {
    expect(taskQuery(EMPTY_FILTERS, null)).toEqual({ page_size: "100" });
    const q = taskQuery({ ...EMPTY_FILTERS, view: "mine", blocked: true, due: "overdue", team: "t1", query: "x" }, "r1");
    expect(q).toEqual({ page_size: "100", filter: "mine", blocked: "1", due: "overdue", team: "t1", room: "r1" });
    expect(activeFilterCount({ ...EMPTY_FILTERS, view: "completed", status: "done" })).toBe(2);
  });

  it("derives who may assign others (Decision 2)", () => {
    expect(assignRole(null)).toBe("member");
    expect(assignRole(access({ org_role: "owner" }))).toBe("owner");
    expect(assignRole(access({ leads_teams: ["t1"] }))).toBe("lead");
    expect(canAssignOthersOn(access({ leads_teams: ["t1"] }), "t1")).toBe(true);
    expect(canAssignOthersOn(access({ leads_teams: ["t1"] }), "t2")).toBe(false);
    expect(canAssignOthersOn(access({ leads_teams: ["t1"] }), null)).toBe(false);
    expect(canAssignOthersOn(access({ org_role: "admin" }), null)).toBe(true);
    expect(canAssignOthersOn(access({}), "t1")).toBe(false);
  });

  it("checks the create form", () => {
    const form = { title: " ", description: "", assignees: [], due_on: "", priority: "normal", team: "", project: "" };
    expect(newTaskProblem(form, "me")).toBe("Give the task a name.");
    expect(newTaskProblem({ ...form, title: "x", assignees: ["you"] }, "me")).toBe("Set a due date when you assign someone else.");
    expect(newTaskProblem({ ...form, title: "x", assignees: ["me"] }, "me")).toBeNull();
    expect(newTaskBody({ ...form, title: " Ship ", assignees: [] }, "r1")).toMatchObject({ title: "Ship", room: "r1", due_on: null, assignees: undefined });
    expect(priorityTone("urgent")).toBe("bad");
  });
});
