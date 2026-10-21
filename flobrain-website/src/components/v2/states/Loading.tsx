"use client";

import { useTr } from "@/i18n/phrases";

export function Loading({ label }: { label?: string }) {
  const tr = useTr();
  return (
    <div role="status" className="p-6 text-[color:var(--fb-v2-text-muted)]">
      {label ?? tr("Loading")}…
    </div>
  );
}
