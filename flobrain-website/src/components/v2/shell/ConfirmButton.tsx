"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";

/**
 * A button that asks before it acts (R7): the first press shows what will happen and a Confirm
 * button; optionally a reason field whose text is passed to ``onConfirm``.
 */
export function ConfirmButton({
  label,
  question,
  confirmLabel,
  onConfirm,
  variant = "outline",
  withReason = false,
  disabled = false,
}: {
  label: string;
  question: string;
  confirmLabel?: string;
  onConfirm: (reason: string) => Promise<void> | void;
  variant?: "default" | "outline" | "ghost" | "danger" | "waiting";
  withReason?: boolean;
  disabled?: boolean;
}) {
  const tr = useTr();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  if (!asking) {
    return (
      <Button type="button" variant={variant} disabled={disabled} onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <div role="group" aria-label={question} className="w-full rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
      <p className="mb-2 text-sm">{question}</p>
      {withReason ? (
        <label className="mb-2 block text-sm">
          <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Reason (optional)")}</span>
          <input className="v2-input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
        </label>
      ) : null}
      <div className="flex gap-2">
        <Button
          type="button"
          variant={variant === "danger" ? "danger" : "default"}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm(reason.trim());
              setAsking(false);
              setReason("");
            } finally {
              setBusy(false);
            }
          }}
        >
          {confirmLabel ?? tr("Confirm")}
        </Button>
        <Button type="button" variant="ghost" disabled={busy} onClick={() => setAsking(false)}>
          {tr("Cancel")}
        </Button>
      </div>
    </div>
  );
}
