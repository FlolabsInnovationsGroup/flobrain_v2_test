import { describe, expect, it } from "vitest";

import {
  formatBlockedDuration,
  isMissionControlEmpty,
  metricCards,
  workloadDrilldown,
} from "./missionControl";

describe("mission control logic", () => {
  it("builds metric cards and drill-down", () => {
    const cards = metricCards({ assigned_open: 2, assigned_done: 1, blocked: 1, overdue: 0 });
    expect(cards.map((card) => card.value)).toEqual([2, 1, 1, 0]);
    const row = { user_id: "u1", open_tasks: 3, done_tasks: 1, seconds_7d: 3600, task_ids: ["t1"] };
    expect(workloadDrilldown([row], "u1")?.task_ids).toEqual(["t1"]);
    expect(workloadDrilldown([row], "missing")).toBeNull();
  });

  it("formats blocker duration and empty state", () => {
    expect(formatBlockedDuration(90)).toBe("1m");
    expect(formatBlockedDuration(90000)).toBe("1d");
    expect(isMissionControlEmpty({ assigned_open: 0, accomplishments: [], blockers: [], deadlines: [], workload: [] })).toBe(
      true,
    );
    expect(isMissionControlEmpty({ assigned_open: 1, accomplishments: [], blockers: [], deadlines: [] })).toBe(false);
  });
});
