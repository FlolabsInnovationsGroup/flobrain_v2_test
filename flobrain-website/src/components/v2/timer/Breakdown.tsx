"use client";

import { useTr } from "@/i18n/phrases";
import { formatDuration, share } from "@/lib/v2/screens/time";

export type BreakdownRow = { key: string; label: string; seconds: number };

/** Horizontal bars, one per row, with h:mm on the end side. Text carries the value, not colour. */
export function Breakdown({ title, rows, empty }: { title: string; rows: BreakdownRow[]; empty?: string }) {
  const tr = useTr();
  const total = rows.reduce((sum, row) => sum + row.seconds, 0);
  return (
    <section className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {rows.length === 0 || total === 0 ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{empty ?? tr("Nothing logged")}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li key={row.key} className="text-sm">
              <div className="mb-1 flex justify-between gap-2">
                <span className="truncate">{row.label}</span>
                <span className="font-mono tabular-nums">{formatDuration(row.seconds)}</span>
              </div>
              <div className="h-1.5 rounded-full bg-[color:var(--fb-v2-border)]" aria-hidden>
                <div className="h-1.5 rounded-full bg-[color:var(--fb-v2-accent)]" style={{ width: `${share(row.seconds, total)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
