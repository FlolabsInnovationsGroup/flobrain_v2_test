"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { errorText } from "@/lib/v2/api";

import { formatClock, initialRecorder, MAX_MS, pickMimeType, recorderReducer } from "./recorderState";

type Props = {
  /** Called with the finished recording. Throw to show the error. */
  onRecorded: (blob: Blob, chosenType: string, durationMs: number) => Promise<void>;
  disabled?: boolean;
  /** Accessible name of the record button. */
  label?: string;
  /** Shown while the recording uploads ("Sending…", "Transcribing…"). */
  busyLabel?: string;
};

function MicIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

/**
 * Hold to record and release to send, or tap (Enter/Space) to start and tap again to send.
 * Escape or Cancel throws the recording away. Stops by itself at 5 minutes.
 */
export function VoiceRecorder({ onRecorded, disabled, label, busyLabel }: Props) {
  const tr = useTr();
  const [state, dispatch] = useReducer(recorderReducer, initialRecorder);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const chosen = useRef("");
  const phase = useRef(state.phase);
  phase.current = state.phase;

  const release = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);

  // Ask for the microphone when a recording starts.
  useEffect(() => {
    if (state.phase !== "requesting") return;
    if (typeof window === "undefined" || typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      dispatch({ type: "unsupported" });
      return;
    }
    let active = true;
    navigator.mediaDevices
      .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((media) => {
        if (!active || phase.current !== "requesting") {
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        stream.current = media;
        chosen.current = pickMimeType(MediaRecorder.isTypeSupported?.bind(MediaRecorder));
        const rec = chosen.current ? new MediaRecorder(media, { mimeType: chosen.current }) : new MediaRecorder(media);
        chunks.current = [];
        rec.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) chunks.current.push(event.data);
        };
        rec.onstop = () => {
          release();
          dispatch({ type: "stopped" });
        };
        recorder.current = rec;
        rec.start(1000);
        dispatch({ type: "granted", at: now() });
      })
      .catch((err: { name?: string }) => {
        if (!active) return;
        if (err?.name === "NotAllowedError" || err?.name === "SecurityError") dispatch({ type: "denied" });
        else if (err?.name === "NotFoundError") dispatch({ type: "failed", error: "no_microphone" });
        else dispatch({ type: "failed", error: "start_failed" });
      });
    return () => {
      active = false;
    };
  }, [state.phase, release]);

  // Visible timer and the 5-minute cap.
  useEffect(() => {
    if (state.phase !== "recording") return;
    const timer = window.setInterval(() => dispatch({ type: "tick", at: now() }), 250);
    return () => window.clearInterval(timer);
  }, [state.phase]);

  // Stop the recorder when the reducer says so (send or discard).
  useEffect(() => {
    if (state.phase !== "stopping") return;
    const rec = recorder.current;
    if (rec && rec.state !== "inactive") rec.stop();
    else {
      release();
      dispatch({ type: "stopped" });
    }
  }, [state.phase, release]);

  // Hand the finished recording over.
  const elapsed = state.elapsedMs;
  useEffect(() => {
    if (state.phase !== "uploading") return;
    const type = recorder.current?.mimeType || chosen.current;
    const blob = new Blob(chunks.current, type ? { type } : undefined);
    chunks.current = [];
    onRecorded(blob, type, elapsed)
      .then(() => dispatch({ type: "uploaded" }))
      .catch((err) => dispatch({ type: "failed", error: errorText(err) }));
    // Runs once per upload; ``elapsed`` is frozen while uploading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase]);

  // Leaving the page mid-recording releases the microphone.
  useEffect(
    () => () => {
      if (recorder.current && recorder.current.state !== "inactive") {
        recorder.current.onstop = null;
        recorder.current.stop();
      }
      release();
    },
    [release],
  );

  const recording = state.phase === "recording";
  const busy = state.phase === "requesting" || state.phase === "stopping" || state.phase === "uploading";
  const holding = recording && state.mode === "pending";

  const message =
    state.phase === "denied"
      ? tr("Microphone access is blocked. Allow it in your browser settings, then try again.")
      : state.phase === "unsupported"
        ? tr("This browser can't record audio.")
        : state.phase === "error"
          ? state.error === "no_microphone"
            ? tr("No microphone was found.")
            : state.error === "start_failed"
              ? tr("Recording could not start. Try again.")
              : state.error
          : "";
  const hint =
    state.notice === "too_short"
      ? tr("Too short. Hold to record, or tap once to start and again to send.")
      : state.notice === "capped"
        ? tr("Voice notes stop at 5 minutes. Sent what you recorded.")
        : state.notice === "cancelled"
          ? tr("Recording cancelled.")
          : "";

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2" onKeyDown={(e) => e.key === "Escape" && (recording || state.phase === "requesting") && dispatch({ type: "cancel" })}>
      {recording ? (
        <span className="flex items-center gap-2 text-sm" aria-hidden>
          <span className="inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-[color:var(--fb-v2-accent)]" />
          <bdi className="v2-mono tabular-nums">
            {formatClock(state.elapsedMs)} / {formatClock(MAX_MS)}
          </bdi>
        </span>
      ) : null}
      <Button
        type="button"
        variant={recording ? "default" : "outline"}
        disabled={disabled || state.phase === "unsupported" || state.phase === "stopping" || state.phase === "uploading"}
        aria-pressed={recording}
        aria-label={recording ? tr("Stop and send voice note") : label || tr("Record a voice note")}
        title={recording ? tr("Stop and send") : tr("Hold to record, or tap to start")}
        className="select-none gap-1 [touch-action:none] [-webkit-touch-callout:none]"
        onContextMenu={(e) => e.preventDefault()}
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          e.currentTarget.releasePointerCapture?.(e.pointerId); // let pointerleave fire when the finger slides away
          dispatch({ type: "press", at: now() });
        }}
        onPointerUp={() => dispatch({ type: "release", at: now() })}
        onPointerLeave={() => holding && dispatch({ type: "cancel" })}
        onClick={(e) => {
          if (e.detail === 0) dispatch({ type: "toggle", at: now() }); // Enter or Space
        }}
      >
        <MicIcon />
        <span className="sr-only sm:not-sr-only">{recording ? tr("Send") : busy ? busyLabel || tr("Working…") : tr("Voice note")}</span>
      </Button>
      {recording || state.phase === "requesting" ? (
        <Button type="button" variant="ghost" onClick={() => dispatch({ type: "cancel" })}>
          {tr("Cancel")}
        </Button>
      ) : null}
      <span role="status" aria-live="polite" className="sr-only">
        {recording ? tr("Recording") : state.phase === "uploading" ? busyLabel || tr("Working…") : ""}
      </span>
      {holding ? <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Release to send. Slide away to cancel.")}</span> : null}
      {message ? (
        <p role="alert" className="basis-full text-sm text-[color:var(--fb-v2-error)]">
          {message}
        </p>
      ) : null}
      {hint ? <p className="basis-full text-xs text-[color:var(--fb-v2-text-muted)]">{hint}</p> : null}
    </div>
  );
}
