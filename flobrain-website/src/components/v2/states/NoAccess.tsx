"use client";

import { useTr } from "@/i18n/phrases";

export function NoAccess({ label }: { label?: string }) {
  const tr = useTr();
  return (
    <div className="p-6 text-[color:var(--fb-v2-error)]" role="alert">
      {label ?? tr("You do not have access")}
    </div>
  );
}
