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
