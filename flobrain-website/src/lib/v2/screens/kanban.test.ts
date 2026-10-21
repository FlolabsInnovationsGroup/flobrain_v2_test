import { describe, expect, it } from "vitest";

import { filterKanbanTasks, groupKanbanTasks, nextKanbanStatuses } from "./kanban";

const tasks = [
  { id: "1", title: "Write tests", status: "to_do", assignees: ["ada"] },
  { id: "2", title: "Ship", status: "in_progress", assignees: ["ben"] },
  { id: "3", title: "Done work", status: "done", assignees: ["ada"] },
];

describe("kanban logic", () => {
  it("groups columns and filters", () => {
    const grouped = groupKanbanTasks(tasks, { query: "ship" });
    expect(grouped.to_do).toHaveLength(0);
    expect(grouped.in_progress).toHaveLength(1);
    expect(filterKanbanTasks(tasks, { assignee: "ada" })).toHaveLength(2);
  });

  it("offers the other two columns as move targets", () => {
    expect(nextKanbanStatuses("to_do").map((column) => column.id)).toEqual(["in_progress", "done"]);
  });
});

import { beforeForStep, moveTask, neighbourColumn } from "./kanban";

describe("kanban moves", () => {
  const board = [
    { id: "a", title: "A", status: "to_do", position: 0 },
    { id: "b", title: "B", status: "to_do", position: 1 },
    { id: "c", title: "C", status: "to_do", position: 2 },
    { id: "d", title: "D", status: "done", position: 0 },
  ];
  const order = (tasks: typeof board, status: string) =>
    groupKanbanTasks(tasks)[status as "to_do"].map((t) => t.id);

  it("reorders inside a column like the server", () => {
    const moved = moveTask(board, "c", "to_do", "a");
    expect(order(moved, "to_do")).toEqual(["c", "a", "b"]);
  });

  it("moves across columns and closes the gap", () => {
    const moved = moveTask(board, "a", "done", null);
    expect(order(moved, "done")).toEqual(["d", "a"]);
    expect(order(moved, "to_do")).toEqual(["b", "c"]);
    expect(moved.find((t) => t.id === "b")?.position).toBe(0);
  });

  it("finds the target for up and down buttons", () => {
    const column = groupKanbanTasks(board).to_do;
    expect(beforeForStep(column, "a", -1)).toBeUndefined();
    expect(beforeForStep(column, "b", -1)).toBe("a");
    expect(beforeForStep(column, "a", 1)).toBe("c");
    expect(beforeForStep(column, "b", 1)).toBeNull();
    expect(beforeForStep(column, "c", 1)).toBeUndefined();
    expect(order(moveTask(board, "a", "to_do", beforeForStep(column, "a", 1) ?? null), "to_do")).toEqual(["b", "a", "c"]);
  });

  it("knows the neighbouring columns", () => {
    expect(neighbourColumn("to_do", -1)).toBeNull();
    expect(neighbourColumn("to_do", 1)).toBe("in_progress");
    expect(neighbourColumn("done", 1)).toBeNull();
  });
});
