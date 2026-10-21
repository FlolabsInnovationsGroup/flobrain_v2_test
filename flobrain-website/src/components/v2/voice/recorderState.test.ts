import { describe, expect, it } from "vitest";

import {
  formatClock,
  HOLD_MS,
  initialRecorder,
  MAX_MS,
  MIN_MS,
  pickMimeType,
  recorderReducer,
  uploadFile,
  type RecorderAction,
  type RecorderState,
} from "./recorderState";
import { hasPending, hasUnchecked, languageLabel, type VoiceNoteRow } from "./voiceApi";

const run = (actions: RecorderAction[], from: RecorderState = initialRecorder) => actions.reduce(recorderReducer, from);

describe("voice recorder reducer", () => {
  it("hold to record: a long press sends on release", () => {
    const s = run([
      { type: "press", at: 0 },
      { type: "granted", at: 50 },
      { type: "tick", at: 2050 },
      { type: "release", at: 2100 },
    ]);
    expect(s.phase).toBe("stopping");
    expect(s.outcome).toBe("send");
    expect(s.mode).toBe("hold");
    expect(recorderReducer(s, { type: "stopped" }).phase).toBe("uploading");
  });

  it("tap to toggle: a short press keeps recording until the next press", () => {
    let s = run([
      { type: "press", at: 0 },
      { type: "granted", at: 20 },
      { type: "release", at: HOLD_MS - 100 },
    ]);
    expect(s.phase).toBe("recording");
    expect(s.mode).toBe("toggle");
    s = run([{ type: "tick", at: 5020 }, { type: "press", at: 5100 }], s);
    expect(s.phase).toBe("stopping");
    expect(s.outcome).toBe("send");
    // The release after the stopping press changes nothing.
    expect(recorderReducer(s, { type: "release", at: 5200 })).toBe(s);
  });

  it("keyboard toggle starts and sends", () => {
    let s = run([{ type: "toggle", at: 0 }, { type: "granted", at: 10 }, { type: "tick", at: 3010 }]);
    expect(s.phase).toBe("recording");
    expect(s.elapsedMs).toBe(3000);
    s = recorderReducer(s, { type: "toggle", at: 3100 });
    expect(s.outcome).toBe("send");
  });

  it("releasing while the browser still asks for the mic switches to tap mode", () => {
    const s = run([{ type: "press", at: 0 }, { type: "release", at: 2000 }]);
    expect(s.phase).toBe("requesting");
    expect(s.mode).toBe("toggle");
    expect(recorderReducer(s, { type: "granted", at: 2100 }).phase).toBe("recording");
  });

  it("cancel throws the recording away", () => {
    let s = run([{ type: "toggle", at: 0 }, { type: "granted", at: 0 }, { type: "tick", at: 4000 }, { type: "cancel" }]);
    expect(s.outcome).toBe("discard");
    s = recorderReducer(s, { type: "stopped" });
    expect(s.phase).toBe("idle");
    expect(s.notice).toBe("cancelled");
  });

  it("cancel before the mic is granted ignores the late grant", () => {
    const s = run([{ type: "press", at: 0 }, { type: "cancel" }, { type: "granted", at: 100 }]);
    expect(s.phase).toBe("idle");
  });

  it("stops by itself at 5 minutes and still sends", () => {
    const s = run([{ type: "toggle", at: 0 }, { type: "granted", at: 0 }, { type: "tick", at: MAX_MS + 300 }]);
    expect(s.phase).toBe("stopping");
    expect(s.outcome).toBe("send");
    expect(s.elapsedMs).toBe(MAX_MS);
    expect(s.notice).toBe("capped");
    const done = run([{ type: "stopped" }, { type: "uploaded" }], s);
    expect(done.phase).toBe("idle");
    expect(done.notice).toBe("capped");
  });

  it("drops recordings that are too short", () => {
    const s = run([{ type: "toggle", at: 0 }, { type: "granted", at: 0 }, { type: "tick", at: MIN_MS - 200 }, { type: "toggle", at: MIN_MS - 100 }, { type: "stopped" }]);
    expect(s.phase).toBe("idle");
    expect(s.notice).toBe("too_short");
  });

  it("permission denied, unsupported and upload errors can be retried", () => {
    const denied = run([{ type: "press", at: 0 }, { type: "denied" }]);
    expect(denied.phase).toBe("denied");
    expect(recorderReducer(denied, { type: "press", at: 10 }).phase).toBe("requesting");
    expect(run([{ type: "unsupported" }]).phase).toBe("unsupported");
    const failed = run([{ type: "failed", error: "Too many requests" }]);
    expect(failed.error).toBe("Too many requests");
    expect(recorderReducer(failed, { type: "toggle", at: 0 }).phase).toBe("requesting");
  });

  it("ignores events that do not fit the phase", () => {
    expect(recorderReducer(initialRecorder, { type: "tick", at: 1000 })).toBe(initialRecorder);
    expect(recorderReducer(initialRecorder, { type: "stopped" })).toBe(initialRecorder);
    expect(recorderReducer(initialRecorder, { type: "uploaded" })).toBe(initialRecorder);
    expect(recorderReducer(initialRecorder, { type: "release", at: 1 })).toBe(initialRecorder);
  });
});

describe("voice helpers", () => {
  it("formats the clock", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(65_400)).toBe("1:05");
    expect(formatClock(MAX_MS)).toBe("5:00");
  });

  it("falls back to MP4 when WebM is not supported (Safari)", () => {
    expect(pickMimeType((t) => t.startsWith("audio/webm"))).toBe("audio/webm;codecs=opus");
    expect(pickMimeType((t) => t.startsWith("audio/mp4"))).toBe("audio/mp4;codecs=mp4a.40.2");
    expect(pickMimeType(() => false)).toBe("");
    expect(pickMimeType(undefined)).toBe("");
    expect(
      pickMimeType(() => {
        throw new Error("old browser");
      }),
    ).toBe("");
  });

  it("names the upload after its real type", () => {
    expect(uploadFile("audio/mp4;codecs=mp4a.40.2", "")).toEqual({ type: "audio/mp4", name: "voice.m4a" });
    expect(uploadFile("", "audio/webm;codecs=opus")).toEqual({ type: "audio/webm", name: "voice.webm" });
    expect(uploadFile("audio/ogg", "")).toEqual({ type: "audio/ogg", name: "voice.ogg" });
    expect(uploadFile("", "")).toEqual({ type: "audio/webm", name: "voice.webm" });
  });

  it("labels Arabic dialects", () => {
    const tr = (s: string) => s;
    expect(languageLabel("ar-EG", tr)).toBe("Egyptian Arabic");
    expect(languageLabel("ar-AE", tr)).toBe("Gulf Arabic");
    expect(languageLabel("ar-SA", tr)).toBe("Gulf Arabic");
    expect(languageLabel("ar", tr)).toBe("Arabic");
    expect(languageLabel("en", tr)).toBe("English");
    expect(languageLabel("de", tr)).toBe("de");
    expect(languageLabel("", tr)).toBe("");
  });

  it("knows when to fetch voice notes again", () => {
    const note = { status: "pending" } as VoiceNoteRow;
    expect(hasUnchecked(["a", "b"], new Set(["a"]))).toBe(true);
    expect(hasUnchecked(["a"], new Set(["a"]))).toBe(false);
    expect(hasPending({ a: note })).toBe(true);
    expect(hasPending({ a: { ...note, status: "done" } })).toBe(false);
  });
});
