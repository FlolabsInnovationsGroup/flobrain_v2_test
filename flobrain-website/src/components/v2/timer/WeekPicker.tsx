"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { mondayOf, shiftWeek, weekEnd } from "@/lib/v2/screens/time";

function short(day: string) {
  const d = new Date(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10));
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Previous / this / next week. ``value`` is the Monday as YYYY-MM-DD. */
export function WeekPicker({ value, onChange }: { value: string; onChange: (monday: string) => void }) {
  const tr = useTr();
  const current = mondayOf(new Date());
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={tr("Week")}>
      <Button type="button" variant="ghost" aria-label={tr("Previous week")} onClick={() => onChange(shiftWeek(value, -1))}>
        <ChevronLeft aria-hidden className="size-4 rtl:rotate-180" />
      </Button>
      <span className="min-w-36 text-center text-sm font-medium">
        {tr("{from} to {to}", { from: short(value), to: short(weekEnd(value)) })}
      </span>
      <Button type="button" variant="ghost" aria-label={tr("Next week")} disabled={value >= current} onClick={() => onChange(shiftWeek(value, 1))}>
        <ChevronRight aria-hidden className="size-4 rtl:rotate-180" />
      </Button>
      {value !== current ? (
        <Button type="button" variant="outline" onClick={() => onChange(current)}>
          {tr("This week")}
        </Button>
      ) : null}
    </div>
  );
}
