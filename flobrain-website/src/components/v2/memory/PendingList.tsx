"use client";

import { Button } from "@/components/v2/ui/button";
import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { categoryLabel, type MemoryItem } from "./types";

/** Suggestions waiting for the person's yes or no (amber: waiting for you). */
export function PendingList({ items, onKeep, onDrop }: { items: MemoryItem[]; onKeep: (item: MemoryItem) => void; onDrop: (item: MemoryItem) => void }) {
  const tr = useTr();
  if (!items.length) return null;
  return (
    <section aria-labelledby="memory-pending" className="mb-8 rounded-xl border border-[color:var(--fb-v2-waiting)] p-4">
      <h2 id="memory-pending" className="mb-1 font-semibold text-[color:var(--fb-v2-waiting)]">
        {tr("{n} suggestion(s) waiting for you", { n: items.length })}
      </h2>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("A buddy noticed these in your chats. Nothing is used until you say yes.")}</p>
      <ul className="flex flex-col gap-3">
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 flex-1 basis-64">
              <p className="break-words" dir="auto">
                {item.text}
              </p>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
                <Badge>{categoryLabel(tr, item.category)}</Badge>
                {item.buddy ? <span>{tr("From {name}", { name: item.buddy.name })}</span> : null}
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="waiting" onClick={() => onKeep(item)}>
                {tr("Yes, remember")}
              </Button>
              <Button variant="ghost" onClick={() => onDrop(item)}>
                {tr("No")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
