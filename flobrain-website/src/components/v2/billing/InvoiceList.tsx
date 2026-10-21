"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import type { Invoice } from "./billing";
import { formatMoney } from "./pricing";

const STATUS: Record<string, string> = { paid: "Paid", open: "Due", draft: "Upcoming", void: "Void", uncollectible: "Not collected" };

/** Invoices copied from Stripe (or the demo's samples). The PDF and payment live at Stripe. */
export function InvoiceList({ invoices, locale }: { invoices: Invoice[]; locale: string }) {
  const tr = useTr();
  const period = (i: Invoice) => {
    if (!i.period_start) return "";
    try {
      return new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(new Date(i.period_start));
    } catch {
      return i.period_start.slice(0, 7);
    }
  };
  if (!invoices.length) return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No invoices yet.")}</p>;
  return (
    <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
      <table className="w-full text-sm">
        <thead className="text-[color:var(--fb-v2-text-muted)]">
          <tr>
            <th className="px-4 py-2 text-start font-normal">{tr("Invoice")}</th>
            <th className="px-4 py-2 text-start font-normal">{tr("Period")}</th>
            <th className="px-4 py-2 text-end font-normal">{tr("Amount")}</th>
            <th className="px-4 py-2 text-start font-normal">{tr("Status")}</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((i) => (
            <tr key={i.id} className="border-t border-[color:var(--fb-v2-border)]">
              <td className="px-4 py-2">
                {i.url ? (
                  <a className="underline underline-offset-2" href={i.url} target="_blank" rel="noopener noreferrer">
                    {i.number || tr("Invoice")}
                  </a>
                ) : (
                  <span>{i.number || tr("Invoice")}</span>
                )}
                {i.demo ? <span className="ms-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Sample")}</span> : null}
              </td>
              <td className="px-4 py-2">{period(i)}</td>
              <td className="px-4 py-2 text-end tabular-nums">{formatMoney(i.amount_cents, locale, i.currency || "USD")}</td>
              <td className="px-4 py-2">
                <Badge tone={i.status === "paid" ? "good" : i.status === "uncollectible" ? "bad" : "neutral"}>
                  {STATUS[i.status] ? tr(STATUS[i.status]) : i.status}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
