"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

import { publishStatus } from "./labels";
import { PLATFORM_LABEL, dayKey, monthGrid, whenOf, type PublishJob } from "./model";
import { PublishJobs } from "./PublishJobs";

const TONE_DOT: Record<string, string> = {
  waiting: "bg-[color:var(--fb-v2-waiting)]",
  good: "bg-[color:var(--fb-v2-success)]",
  bad: "bg-[color:var(--fb-v2-error)]",
  accent: "bg-[color:var(--fb-v2-accent)]",
  neutral: "bg-[color:var(--fb-v2-text-muted)]",
};

/** Month view of scheduled and published posts. */
export function ContentCalendar({ orgId }: { orgId: string | null }) {
  const tr = useTr();
  const [month, setMonth] = useState(() => {
    const now = new Date();
    return { y: now.getFullYear(), m: now.getMonth() };
  });
  const [day, setDay] = useState<string | null>(null);
  const days = monthGrid(month.y, month.m);
  const from = days[0].toISOString();
  const to = new Date(days[41].getFullYear(), days[41].getMonth(), days[41].getDate(), 23, 59, 59).toISOString();
  const posts = useOrgData<PublishJob[]>(orgId, `/content/calendar?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
  const rows = Array.isArray(posts.data) ? posts.data : [];
  const byDay = new Map<string, PublishJob[]>();
  for (const job of rows) {
    const at = whenOf(job);
    if (!at) continue;
    const key = dayKey(at);
    byDay.set(key, [...(byDay.get(key) ?? []), job]);
  }
  const today = dayKey(new Date().toISOString());
  const title = new Date(month.y, month.m, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const weekdays = days.slice(0, 7).map((d) => d.toLocaleDateString(undefined, { weekday: "short" }));
  const shown = day ? (byDay.get(day) ?? []) : rows.filter((j) => {
    const at = whenOf(j);
    return at ? new Date(at).getMonth() === month.m : false;
  });

  function step(delta: number) {
    const d = new Date(month.y, month.m + delta, 1);
    setMonth({ y: d.getFullYear(), m: d.getMonth() });
    setDay(null);
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{title}</h2>
        <div className="flex gap-1">
          <Button variant="ghost" onClick={() => step(-1)} aria-label={tr("Previous month")}>
            ‹
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              const now = new Date();
              setMonth({ y: now.getFullYear(), m: now.getMonth() });
              setDay(null);
            }}
          >
            {tr("Today")}
          </Button>
          <Button variant="ghost" onClick={() => step(1)} aria-label={tr("Next month")}>
            ›
          </Button>
        </div>
      </div>
      <ScreenBody state={posts.state} error={posts.error} onRetry={posts.reload}>
        <div className="grid grid-cols-7 gap-px overflow-hidden rounded-xl bg-[color:var(--fb-v2-border)] text-sm">
          {weekdays.map((w) => (
            <div key={w} className="bg-[color:var(--fb-v2-surface)] px-2 py-1 text-xs font-medium text-[color:var(--fb-v2-text-muted)]">
              {w}
            </div>
          ))}
          {days.map((d) => {
            const key = dayKey(d.toISOString());
            const items = byDay.get(key) ?? [];
            const outside = d.getMonth() !== month.m;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setDay(day === key ? null : key)}
                aria-pressed={day === key}
                aria-label={tr("{date}: {n} posts", { date: d.toLocaleDateString(), n: items.length })}
                className={cn(
                  "min-h-20 bg-[color:var(--fb-v2-surface)] p-1.5 text-start align-top",
                  outside && "opacity-50",
                  day === key && "ring-2 ring-inset ring-[color:var(--fb-v2-accent)]",
                )}
              >
                <span className={cn("text-xs", key === today && "rounded bg-[color:var(--fb-v2-accent)] px-1 text-white")}>{d.getDate()}</span>
                <span className="mt-1 block space-y-0.5">
                  {items.slice(0, 3).map((j) => (
                    <span key={j.id} className="flex items-center gap-1 truncate text-xs">
                      <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", TONE_DOT[publishStatus(tr, j.status).tone])} aria-hidden />
                      <span className="truncate">
                        {new Date(whenOf(j) as string).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })} {PLATFORM_LABEL[j.platform] ?? j.platform}
                      </span>
                    </span>
                  ))}
                  {items.length > 3 ? <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} more", { n: items.length - 3 })}</span> : null}
                </span>
              </button>
            );
          })}
        </div>
      </ScreenBody>
      <div className="mt-6" />
      <Section title={day ? tr("Posts on {date}", { date: new Date(`${day}T12:00:00`).toLocaleDateString() }) : tr("Posts this month")}>
        <PublishJobs orgId={orgId} jobs={shown} onChange={posts.reload} emptyLabel={tr("Nothing scheduled.")} />
      </Section>
    </div>
  );
}
