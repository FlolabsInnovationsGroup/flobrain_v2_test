"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import type { InvoiceStatus } from "./types";

type Tone = "neutral" | "waiting" | "good" | "bad" | "accent";

/** Amber only while a person must approve, green when the authority accepted, rose when it did not. */
export function statusTone(status: InvoiceStatus, waiting: boolean): Tone {
  if (waiting) return "waiting";
  if (status === "accepted") return "good";
  if (status === "rejected" || status === "error") return "bad";
  if (status === "submitted") return "accent";
  return "neutral";
}

export function StatusBadge({ status, waiting, simulated }: { status: InvoiceStatus; waiting: boolean; simulated?: boolean }) {
  const tr = useTr();
  const label = waiting
    ? tr("Waiting for approval")
    : status === "draft"
      ? tr("Draft")
      : status === "ready"
        ? tr("Ready to send")
        : status === "submitted"
          ? tr("Submitted, checking")
          : status === "accepted"
            ? tr("Accepted")
            : status === "rejected"
              ? tr("Rejected")
              : tr("Error");
  return (
    <span className="inline-flex items-center gap-1">
      <Badge tone={statusTone(status, waiting)}>{label}</Badge>
      {simulated ? <Badge>{tr("Simulated")}</Badge> : null}
    </span>
  );
}

export function useLabels() {
  const tr = useTr();
  return {
    country: (c: string) => (c === "SA" ? tr("Saudi Arabia (ZATCA)") : tr("Egypt (ETA)")),
    type: (t: string) =>
      t === "standard" ? tr("Standard (B2B)") : t === "simplified" ? tr("Simplified (B2C)") : t === "b2b" ? tr("Business") : tr("Consumer"),
    kind: (k: string) => (k === "credit" ? tr("Credit note") : k === "debit" ? tr("Debit note") : tr("Invoice")),
    authority: (c: string) => (c === "SA" ? "ZATCA" : tr("the ETA")),
  };
}
