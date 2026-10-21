import { describe, expect, it } from "vitest";

import { applyTimerResponse, emptyTimer, timerLabel } from "./timer";

describe("timer logic", () => {
  it("keeps a running timer across a new request and flags 409", () => {
    const started = applyTimerResponse(emptyTimer(), {
      type: "started",
      running: { id: "t1", description: "work" },
    });
    expect(timerLabel(started)).toBe("Timer running");
    const otherDevice = applyTimerResponse(emptyTimer(), { type: "loaded", running: started.running });
    expect(otherDevice.running?.id).toBe("t1");
    const conflict = applyTimerResponse(started, { type: "conflict" });
    expect(conflict.conflict).toBe(true);
    expect(timerLabel(conflict)).toBe("Timer already running");
  });
});
