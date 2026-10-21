/**
 * Voice recorder state, as a pure reducer (W7). The component turns pointer, keyboard and
 * MediaRecorder events into these actions and runs side effects when the phase changes.
 *
 * Two ways to record with one button:
 * - hold: press, speak, release to send (slide off the button or press Escape to cancel);
 * - tap: a short press (or Enter/Space) starts, the next tap sends.
 */

export const MAX_MS = 5 * 60 * 1000;
export const HOLD_MS = 350;
export const MIN_MS = 600;

export type Phase = "idle" | "requesting" | "recording" | "stopping" | "uploading" | "denied" | "unsupported" | "error";
export type Mode = "pending" | "hold" | "toggle";
export type Notice = "" | "too_short" | "capped" | "cancelled";

export type RecorderState = {
  phase: Phase;
  mode: Mode | null;
  pressedAt: number;
  startedAt: number;
  elapsedMs: number;
  /** In "stopping": keep the recording (send) or throw it away. */
  outcome: "send" | "discard" | null;
  notice: Notice;
  error: string;
};

export type RecorderAction =
  | { type: "press"; at: number }
  | { type: "release"; at: number }
  | { type: "toggle"; at: number }
  | { type: "granted"; at: number }
  | { type: "denied" }
  | { type: "unsupported" }
  | { type: "failed"; error: string }
  | { type: "tick"; at: number }
  | { type: "cancel" }
  | { type: "stopped" }
  | { type: "uploaded" }
  | { type: "reset" };

export const initialRecorder: RecorderState = {
  phase: "idle",
  mode: null,
  pressedAt: 0,
  startedAt: 0,
  elapsedMs: 0,
  outcome: null,
  notice: "",
  error: "",
};

const stop = (s: RecorderState, outcome: "send" | "discard", notice: Notice = ""): RecorderState => ({ ...s, phase: "stopping", outcome, notice });

/** Phases a new recording can start from (a past error or denial can be retried). */
const startable = (phase: Phase) => phase === "idle" || phase === "error" || phase === "denied";

export function recorderReducer(s: RecorderState, a: RecorderAction): RecorderState {
  switch (a.type) {
    case "press":
      if (startable(s.phase)) return { ...initialRecorder, phase: "requesting", mode: "pending", pressedAt: a.at };
      if (s.phase === "recording" && s.mode === "toggle") return stop(s, "send");
      return s;
    case "release": {
      if (s.mode !== "pending") return s;
      const held = a.at - s.pressedAt >= HOLD_MS;
      if (s.phase === "recording" && held) return stop({ ...s, mode: "hold" }, "send");
      if (s.phase === "requesting" || s.phase === "recording") return { ...s, mode: "toggle" };
      return s;
    }
    case "toggle":
      if (startable(s.phase)) return { ...initialRecorder, phase: "requesting", mode: "toggle", pressedAt: a.at };
      if (s.phase === "recording") return stop(s, "send");
      return s;
    case "granted":
      if (s.phase !== "requesting") return s; // cancelled while the browser was asking: the component releases the mic
      return { ...s, phase: "recording", startedAt: a.at, elapsedMs: 0 };
    case "denied":
      return s.phase === "requesting" ? { ...initialRecorder, phase: "denied" } : s;
    case "unsupported":
      return { ...initialRecorder, phase: "unsupported" };
    case "failed":
      return { ...initialRecorder, phase: "error", error: a.error };
    case "tick": {
      if (s.phase !== "recording") return s;
      const elapsedMs = Math.max(0, a.at - s.startedAt);
      if (elapsedMs >= MAX_MS) return stop({ ...s, elapsedMs: MAX_MS }, "send", "capped");
      return { ...s, elapsedMs };
    }
    case "cancel":
      if (s.phase === "recording") return stop(s, "discard", "cancelled");
      if (s.phase === "requesting") return { ...initialRecorder, notice: "cancelled" };
      return s;
    case "stopped":
      if (s.phase !== "stopping") return s;
      if (s.outcome === "send" && s.elapsedMs >= MIN_MS) return { ...s, phase: "uploading" };
      return { ...initialRecorder, notice: s.outcome === "send" ? "too_short" : s.notice };
    case "uploaded":
      return s.phase === "uploading" ? { ...initialRecorder, notice: s.notice === "capped" ? "capped" : "" } : s;
    case "reset":
      return initialRecorder;
  }
}

/** "1:05" from milliseconds. */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** Recorder formats in order of preference. Safari (iOS and macOS) records MP4/AAC. */
export const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4;codecs=mp4a.40.2", "audio/mp4"];

export function pickMimeType(isTypeSupported: ((type: string) => boolean) | undefined): string {
  if (!isTypeSupported) return "";
  return MIME_CANDIDATES.find((type) => {
    try {
      return isTypeSupported(type);
    } catch {
      return false;
    }
  }) ?? "";
}

/** The upload's file name and bare type from what the recorder produced. */
export function uploadFile(blobType: string, chosen: string): { type: string; name: string } {
  const type = (blobType || chosen || "audio/webm").split(";")[0].trim().toLowerCase();
  const ext = type.includes("mp4") || type.includes("m4a") ? "m4a" : type.includes("ogg") ? "ogg" : type.includes("mpeg") ? "mp3" : "webm";
  return { type, name: `voice.${ext}` };
}
