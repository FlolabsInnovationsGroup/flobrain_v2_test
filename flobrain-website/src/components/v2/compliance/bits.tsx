"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { clampPct, statusTone } from "./logic";
import type { CheckStatus } from "./types";

export function StatusBadge({ status }: { status: CheckStatus }) {
  const tr = useTr();
  const label =
    status === "pass" ? tr("Passing") : status === "fail" ? tr("Gap") : status === "manual" ? tr("Needs evidence") : tr("Not applicable");
  return <Badge tone={statusTone(status)}>{label}</Badge>;
}

/** A readiness bar: the filled part is the share of applicable controls passing. */
export function ReadinessBar({ value, label, size = "md" }: { value: number; label: string; size?: "sm" | "md" }) {
  const pct = clampPct(value);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className={`w-full overflow-hidden rounded-full bg-[color:var(--fb-v2-track)] ${size === "sm" ? "h-1.5" : "h-2.5"}`}
    >
      <div className="h-full rounded-full bg-[color:var(--fb-v2-accent)]" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Pct({ value }: { value: number }) {
  return <span className="v2-mono tabular-nums">{clampPct(value)}%</span>;
}

/** A tab strip that keeps the selected tab in the URL. Arrow keys move between tabs. */
export function Tabs<T extends string>({ tabs, current, onChange, label }: { tabs: { key: T; label: string; count?: number }[]; current: T; onChange: (t: T) => void; label: string }) {
  function onKey(e: React.KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((t) => t.key === current);
    const rtl = typeof document !== "undefined" && document.dir === "rtl";
    const fwd = rtl ? "ArrowLeft" : "ArrowRight";
    const back = rtl ? "ArrowRight" : "ArrowLeft";
    if (e.key === fwd) onChange(tabs[(i + 1) % tabs.length].key);
    else if (e.key === back) onChange(tabs[(i - 1 + tabs.length) % tabs.length].key);
    else return;
    e.preventDefault();
  }
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className="-mx-1 mb-6 flex gap-1 overflow-x-auto border-b border-[color:var(--fb-v2-border)] px-1">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          type="button"
          aria-selected={current === t.key}
          tabIndex={current === t.key ? 0 : -1}
          onClick={() => onChange(t.key)}
          className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
            current === t.key ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]"
          }`}
        >
          {t.label}
          {t.count ? <span className="v2-mono ms-1.5 rounded-full bg-[color:var(--fb-v2-raised)] px-1.5 text-xs">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export const inputClass = "v2-input text-sm";
