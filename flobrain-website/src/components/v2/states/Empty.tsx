"use client";

import { useTr } from "@/i18n/phrases";

export function Empty({ label }: { label?: string }) {
  const tr = useTr();
  return (
    <div className="p-6 text-[color:var(--fb-v2-text-muted)]">{label ?? tr("No data yet")}</div>
  );
}
