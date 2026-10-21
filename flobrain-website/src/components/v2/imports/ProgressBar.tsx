"use client";

import { useTr } from "@/i18n/phrases";

/** A bar that fills from the start side (right in Arabic). ``value`` null shows a moving stripe. */
export function ProgressBar({ value, label }: { value: number | null; label: string }) {
  const tr = useTr();
  return (
    <div>
      <div className="mb-1 flex justify-between gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
        <span>{label}</span>
        <span className="v2-mono">{value === null ? tr("Working…") : `${value}%`}</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value ?? undefined}
        className="h-2 overflow-hidden rounded-full bg-[color:var(--fb-v2-track)]"
      >
        <div
          className={`h-full rounded-full bg-[color:var(--fb-v2-accent)] transition-[width] duration-500 ${value === null ? "w-1/3 animate-pulse" : ""}`}
          style={value === null ? undefined : { width: `${value}%` }}
        />
      </div>
    </div>
  );
}
