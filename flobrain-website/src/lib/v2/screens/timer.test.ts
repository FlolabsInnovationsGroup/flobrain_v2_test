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

import { clockSkew, elapsedSeconds } from "./timer";

describe("timer clock", () => {
  it("counts from the server's start time with the server's clock", () => {
    const running = { id: "t", description: "", started_at: "2026-10-21T10:00:00Z" };
    const browser = new Date("2026-10-21T10:00:30Z").getTime();
    expect(elapsedSeconds(running, browser)).toBe(30);
    const skew = clockSkew("2026-10-21T10:01:00Z", browser);
    expect(elapsedSeconds(running, browser, skew)).toBe(60);
    expect(elapsedSeconds(null, browser)).toBe(0);
    expect(clockSkew(undefined, browser)).toBe(0);
  });
});
