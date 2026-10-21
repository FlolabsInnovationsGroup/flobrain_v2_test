"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { cn } from "@/lib/utils";

import {
  addCut,
  addKeep,
  clock,
  keptMask,
  removedMask,
  removeFillers,
  restoreRange,
  spanOf,
  wordAt,
  type Clip,
  type Op,
  type Word,
} from "./model";

/**
 * Text-based editing: select words (click, then shift-click to extend) and cut or restore them.
 * Removed words are struck through; suggested clips are highlighted; the playing word is underlined.
 * Every change is a new EDL version, saved by the parent.
 */
export function TranscriptEditor({
  words,
  ops,
  asset,
  clips,
  currentTime,
  busy,
  onSeek,
  onChange,
}: {
  words: Word[];
  ops: Op[];
  asset: string;
  clips: Clip[];
  currentTime: number;
  busy: boolean;
  onSeek: (t: number) => void;
  onChange: (ops: Op[], note: string) => void;
}) {
  const tr = useTr();
  const [anchor, setAnchor] = useState<number | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const removed = useMemo(() => removedMask(words, ops, asset), [words, ops, asset]);
  const kept = useMemo(() => keptMask(words, ops, asset), [words, ops, asset]);
  const inClip = useMemo(
    () => words.map((w) => clips.some((c) => c.asset === asset && c.start <= w.start && w.end <= c.end)),
    [words, clips, asset],
  );
  const playing = wordAt(words, currentTime);
  const sel = anchor === null ? null : ([Math.min(anchor, focus ?? anchor), Math.max(anchor, focus ?? anchor)] as const);
  const removedCount = removed.filter(Boolean).length;

  function pick(i: number, extend: boolean) {
    if (extend && anchor !== null) setFocus(i);
    else {
      setAnchor(i);
      setFocus(i);
    }
  }

  function clear() {
    setAnchor(null);
    setFocus(null);
  }

  function act(kind: "cut" | "restore" | "keep") {
    if (!sel) return;
    const [a, b] = sel;
    const span = spanOf(words, a, b);
    if (kind === "cut") onChange(addCut(ops, asset, words, a, b), `cut ${clock(span.start)}-${clock(span.end)}`);
    if (kind === "restore") onChange(restoreRange(ops, asset, words, a, b), `restore ${clock(span.start)}-${clock(span.end)}`);
    if (kind === "keep") onChange(addKeep(ops, asset, words, a, b), `segment ${clock(span.start)}-${clock(span.end)}`);
    clear();
  }

  if (!words.length) return null;
  const selectionHasRemoved = sel ? removed.slice(sel[0], sel[1] + 1).some(Boolean) : false;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2" role="toolbar" aria-label={tr("Transcript tools")}>
        {sel ? (
          <>
            <span className="text-sm text-[color:var(--fb-v2-text-muted)]">
              {tr("{n} words selected, {from} to {to}", {
                n: sel[1] - sel[0] + 1,
                from: clock(words[sel[0]].start),
                to: clock(words[sel[1]].end),
              })}
            </span>
            <Button variant="danger" disabled={busy} onClick={() => act("cut")}>
              {tr("Cut")}
            </Button>
            {selectionHasRemoved ? (
              <Button variant="outline" disabled={busy} onClick={() => act("restore")}>
                {tr("Restore")}
              </Button>
            ) : null}
            <Button variant="outline" disabled={busy} onClick={() => act("keep")}>
              {tr("Keep as segment")}
            </Button>
            <Button variant="ghost" onClick={() => onSeek(words[sel[0]].start)}>
              {tr("Play from here")}
            </Button>
            <Button variant="ghost" onClick={clear}>
              {tr("Clear selection")}
            </Button>
          </>
        ) : (
          <>
            <span className="text-sm text-[color:var(--fb-v2-text-muted)]">
              {tr("Click a word, then shift-click another to select. {n} of {total} words removed.", { n: removedCount, total: words.length })}
            </span>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                const result = removeFillers(ops, asset, words);
                if (result.count) onChange(result.ops, `remove ${result.count} filler words`);
              }}
            >
              {tr("Remove filler words")}
            </Button>
          </>
        )}
      </div>
      <div
        className="max-h-80 overflow-y-auto rounded-xl bg-[color:var(--fb-v2-surface)] p-4 leading-8"
        onKeyDown={(e) => {
          if (sel && (e.key === "Delete" || e.key === "Backspace")) {
            e.preventDefault();
            act("cut");
          }
          if (e.key === "Escape") clear();
        }}
      >
        {words.map((w, i) => {
          const selected = sel !== null && i >= sel[0] && i <= sel[1];
          return (
            <span key={`${i}-${w.start}`}>
              <button
                type="button"
                onClick={(e) => pick(i, e.shiftKey)}
                onDoubleClick={() => onSeek(w.start)}
                aria-pressed={selected}
                title={`${clock(w.start)}${removed[i] ? ` · ${tr("removed")}` : ""}`}
                className={cn(
                  "rounded px-0.5",
                  removed[i] && "text-[color:var(--fb-v2-text-muted)] line-through decoration-[color:var(--fb-v2-error)] decoration-2",
                  !kept[i] && !removed[i] && "opacity-50",
                  inClip[i] && !selected && "bg-[color:color-mix(in_srgb,var(--fb-v2-waiting)_14%,transparent)]",
                  selected && "bg-[color:var(--fb-v2-accent)] text-white",
                  i === playing && "underline decoration-[color:var(--fb-v2-accent)] decoration-2 underline-offset-4",
                )}
              >
                {w.w}
              </button>{" "}
            </span>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Double-click a word to play from it. Highlighted words are inside a suggested clip; faded words are outside your segments.")}
      </p>
    </div>
  );
}
