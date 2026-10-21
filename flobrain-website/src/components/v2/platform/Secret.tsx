"use client";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";

/** Secrets are shown once, right after they are made, then never again. */
export function Secret({ label, value }: { label: string; value: string }) {
  const tr = useTr();
  return (
    <div className="my-3 rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]">
      <p className="text-sm font-medium">{tr("{label}. Copy it now: it won't be shown again.", { label })}</p>
      <code className="mt-1 block break-all text-sm">{value}</code>
      <Button className="mt-2" variant="outline" onClick={() => navigator.clipboard?.writeText(value)}>
        {tr("Copy")}
      </Button>
    </div>
  );
}
