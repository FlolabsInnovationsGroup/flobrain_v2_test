"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { errorText } from "@/lib/v2/api";

import { formatClock } from "./recorderState";
import { fetchVoiceAudio, languageLabel, type VoiceNoteRow } from "./voiceApi";

type Props = {
  note: VoiceNoteRow;
  /** Retry a failed transcript (shown to the author only). */
  onRetry?: () => Promise<void>;
};

function PlayIcon({ playing }: { playing: boolean }) {
  return playing ? (
    <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </svg>
  ) : (
    <svg aria-hidden viewBox="0 0 24 24" width="18" height="18" fill="currentColor" className="rtl:-scale-x-100">
      <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" />
    </svg>
  );
}

/** Play a voice note, read its transcript, and see it translated with the original one tap away. */
export function VoiceNotePlayer({ note, onRetry }: Props) {
  const tr = useTr();
  const audio = useRef<HTMLAudioElement | null>(null);
  const [src, setSrc] = useState("");
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [length, setLength] = useState(note.duration || 0);
  const [showText, setShowText] = useState(true);
  const [original, setOriginal] = useState(false);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);

  useEffect(() => () => {
    if (src) URL.revokeObjectURL(src);
  }, [src]);

  async function toggle() {
    setError("");
    const el = audio.current;
    if (!el) return;
    if (playing) {
      el.pause();
      return;
    }
    if (!src) {
      setLoading(true);
      try {
        const url = URL.createObjectURL(await fetchVoiceAudio(note.audio_url));
        el.src = url;
        setSrc(url);
      } catch (err) {
        setError(errorText(err));
        setLoading(false);
        return;
      }
      setLoading(false);
    }
    try {
      await el.play();
    } catch {
      setError(tr("This voice note can't be played here."));
    }
  }

  const from = languageLabel(note.language, tr);
  const translated = note.translated && !!note.translation;
  const text = translated && !original ? note.translation ?? "" : note.transcript;
  const shownLength = Number.isFinite(length) && length > 0 ? length : note.duration;

  return (
    <div className="mt-1 max-w-md rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-raised)] p-2 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="default"
          className="h-9 w-9 shrink-0 rounded-full p-0"
          onClick={toggle}
          disabled={loading}
          aria-label={playing ? tr("Pause voice note") : tr("Play voice note")}
        >
          <PlayIcon playing={playing} />
        </Button>
        <input
          type="range"
          min={0}
          max={shownLength || 0}
          step={0.1}
          value={Math.min(position, shownLength || 0)}
          onChange={(e) => {
            const value = Number(e.target.value);
            setPosition(value);
            if (audio.current && src) audio.current.currentTime = value;
          }}
          disabled={!src}
          aria-label={tr("Position in voice note")}
          aria-valuetext={`${formatClock(position * 1000)} / ${formatClock(shownLength * 1000)}`}
          className="h-1 min-w-0 flex-1 cursor-pointer accent-[color:var(--fb-v2-accent)] disabled:cursor-default"
        />
        <bdi className="v2-mono shrink-0 text-xs tabular-nums text-[color:var(--fb-v2-text-muted)]">
          {src ? `${formatClock(position * 1000)} / ` : ""}
          {formatClock(shownLength * 1000)}
        </bdi>
        <audio
          ref={audio}
          preload="none"
          className="hidden"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => {
            setPlaying(false);
            setPosition(0);
          }}
          onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setLength(e.currentTarget.duration)}
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
        {note.status === "done" && note.transcript ? (
          <button type="button" className="underline-offset-2 hover:underline" aria-expanded={showText} onClick={() => setShowText((v) => !v)}>
            {showText ? tr("Hide transcript") : tr("Show transcript")}
          </button>
        ) : null}
        {translated && showText ? (
          <>
            <span>{original ? (from ? tr("Original in {language}", { language: from }) : tr("Original")) : from ? tr("Translated from {language}", { language: from }) : tr("Translated")}</span>
            <button type="button" className="font-medium text-[color:var(--fb-v2-accent)] underline-offset-2 hover:underline" onClick={() => setOriginal((v) => !v)}>
              {original ? tr("Show translation") : tr("Show original")}
            </button>
          </>
        ) : null}
        {note.demo ? <Badge>{tr("Demo transcript")}</Badge> : null}
      </div>

      {note.status === "pending" ? (
        <p role="status" className="mt-1 animate-pulse text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Transcribing…")}
        </p>
      ) : null}
      {note.status === "failed" ? (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <p className="text-sm text-[color:var(--fb-v2-error)]">{tr("Transcript not available.")}</p>
          {onRetry ? (
            <Button
              type="button"
              variant="ghost"
              className="px-2 py-1 text-xs"
              disabled={retrying}
              onClick={() => {
                setRetrying(true);
                onRetry()
                  .catch((err) => setError(errorText(err)))
                  .finally(() => setRetrying(false));
              }}
            >
              {tr("Try again")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {note.status === "done" && showText && text ? (
        <p className="mt-1 whitespace-pre-wrap break-words text-sm" dir="auto">
          {text}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-1 text-xs text-[color:var(--fb-v2-error)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
