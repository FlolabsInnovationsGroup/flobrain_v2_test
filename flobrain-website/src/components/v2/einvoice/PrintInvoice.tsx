"use client";

import { display } from "./money";
import { QrImage } from "./QrImage";
import type { Invoice } from "./types";

/**
 * The printable tax invoice, in Arabic and English side by side whatever the interface language
 * (ZATCA requires Arabic on tax invoices; a second language is allowed). The bilingual labels below
 * are fixed on purpose and do not go through ``tr()``. The page direction follows the interface:
 * right to left in Arabic, with logical start/end alignment so both directions read correctly.
 * Print it to PDF from the browser; turning that PDF into PDF/A-3 with the XML embedded is a later
 * step (see docs/v2/features/EINVOICE.md).
 */

type Pair = readonly [string, string]; // [English, Arabic]

const L = {
  standard: ["Tax invoice", "فاتورة ضريبية"],
  simplified: ["Simplified tax invoice", "فاتورة ضريبية مبسطة"],
  credit: ["Credit note", "إشعار دائن"],
  debit: ["Debit note", "إشعار مدين"],
  eg: ["Electronic tax invoice", "فاتورة ضريبية إلكترونية"],
  number: ["Invoice number", "رقم الفاتورة"],
  issued: ["Issue date", "تاريخ الإصدار"],
  supply: ["Supply date", "تاريخ التوريد"],
  seller: ["Seller", "البائع"],
  buyer: ["Buyer", "المشتري"],
  vat: ["VAT number", "الرقم الضريبي"],
  taxId: ["Tax registration number", "رقم التسجيل الضريبي"],
  cr: ["Commercial registration", "السجل التجاري"],
  address: ["Address", "العنوان"],
  item: ["Item", "الصنف"],
  qty: ["Qty", "الكمية"],
  price: ["Unit price", "سعر الوحدة"],
  discount: ["Discount", "الخصم"],
  rate: ["VAT %", "نسبة الضريبة"],
  vatAmount: ["VAT", "ضريبة القيمة المضافة"],
  lineTotal: ["Total with VAT", "الإجمالي شامل الضريبة"],
  beforeVat: ["Total before VAT", "الإجمالي قبل الضريبة"],
  totalVat: ["Total VAT", "إجمالي ضريبة القيمة المضافة"],
  total: ["Total due", "الإجمالي المستحق"],
  original: ["Original invoice", "الفاتورة الأصلية"],
  reason: ["Reason", "السبب"],
  etaId: ["ETA document ID", "معرّف المستند لدى المصلحة"],
  counter: ["Invoice counter", "عداد الفاتورة"],
  demo: ["Demo document: not sent to any tax authority", "مستند تجريبي: لم يُرسل إلى أي جهة ضريبية"],
  consumer: ["Consumer", "مستهلك"],
} as const satisfies Record<string, Pair>;

function Label({ pair, className = "" }: { pair: Pair; className?: string }) {
  return (
    <span className={`flex flex-col leading-tight ${className}`}>
      <span lang="ar" dir="rtl" className="font-medium">{pair[1]}</span>
      <span lang="en" dir="ltr" className="text-[11px] opacity-70">{pair[0]}</span>
    </span>
  );
}

function title(invoice: Invoice): Pair {
  if (invoice.country === "EG") return L.eg;
  if (invoice.kind === "credit") return L.credit;
  if (invoice.kind === "debit") return L.debit;
  return invoice.invoice_type === "standard" ? L.standard : L.simplified;
}

export function PrintInvoice({ invoice, dir }: { invoice: Invoice; dir: "ltr" | "rtl" }) {
  const t = title(invoice);
  const places = invoice.country === "SA" ? 2 : 5;
  const amount = (v: string | undefined) => (invoice.country === "SA" ? v ?? "" : display(Number(v ?? 0).toFixed(places)));
  const issued = new Date(invoice.issue_datetime);
  const date = issued.toLocaleString("en-GB", { timeZone: invoice.country === "SA" ? "Asia/Riyadh" : "Africa/Cairo", dateStyle: "medium", timeStyle: "short" });
  const taxLabel = invoice.country === "SA" ? L.vat : L.taxId;
  const cell = "border border-black/20 px-2 py-1 align-top";
  return (
    <article dir={dir} className="einvoice-print mx-auto max-w-[210mm] bg-white p-6 text-[13px] text-black">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-4 border-b border-black/30 pb-3">
        <div>
          <h1 className="text-xl font-bold"><span lang="ar" dir="rtl">{t[1]}</span></h1>
          <p lang="en" dir="ltr" className="text-sm">{t[0]}</p>
          {invoice.simulated ? <p className="mt-1 text-xs"><span lang="ar" dir="rtl">{L.demo[1]}</span> · <span lang="en" dir="ltr">{L.demo[0]}</span></p> : null}
        </div>
        {invoice.qr ? <QrImage value={invoice.qr} size={132} label={`QR ${invoice.number}`} /> : null}
      </header>

      <dl className="mb-4 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        <div><dt><Label pair={L.number} /></dt><dd dir="ltr" className="font-mono text-start">{invoice.number}</dd></div>
        <div><dt><Label pair={L.issued} /></dt><dd dir="ltr" className="text-start">{date}</dd></div>
        {invoice.supply_date ? <div><dt><Label pair={L.supply} /></dt><dd dir="ltr" className="text-start">{invoice.supply_date}</dd></div> : null}
        {invoice.icv ? <div><dt><Label pair={L.counter} /></dt><dd dir="ltr" className="text-start font-mono">{invoice.icv}</dd></div> : null}
        {invoice.authority_uuid ? <div className="col-span-2"><dt><Label pair={L.etaId} /></dt><dd dir="ltr" className="break-all text-start font-mono">{invoice.authority_uuid}</dd></div> : null}
        {invoice.kind !== "invoice" ? (
          <>
            <div><dt><Label pair={L.original} /></dt><dd dir="ltr" className="text-start font-mono">{invoice.billing_reference}</dd></div>
            <div><dt><Label pair={L.reason} /></dt><dd>{invoice.adjustment_reason}</dd></div>
          </>
        ) : null}
      </dl>

      <section className="mb-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded border border-black/20 p-3">
          <h2 className="mb-1"><Label pair={L.seller} /></h2>
          <p className="font-medium">{invoice.seller.name_ar ? <span lang="ar" dir="rtl">{invoice.seller.name_ar} · </span> : null}{invoice.seller.name}</p>
          <p><Label pair={taxLabel} className="inline-flex" /> <span dir="ltr" className="font-mono">{invoice.seller.tax_number}</span></p>
          {invoice.seller.registration_id && invoice.country === "SA" ? <p><Label pair={L.cr} className="inline-flex" /> <span dir="ltr" className="font-mono">{invoice.seller.registration_id}</span></p> : null}
          <p>{invoice.seller.address}</p>
        </div>
        <div className="rounded border border-black/20 p-3">
          <h2 className="mb-1"><Label pair={L.buyer} /></h2>
          <p className="font-medium">{invoice.buyer_name || `${L.consumer[1]} · ${L.consumer[0]}`}</p>
          {invoice.buyer_tax_number ? <p><Label pair={taxLabel} className="inline-flex" /> <span dir="ltr" className="font-mono">{invoice.buyer_tax_number}</span></p> : null}
          <p>{[invoice.buyer_building_number, invoice.buyer_street, invoice.buyer_district, invoice.buyer_city, invoice.buyer_region, invoice.buyer_postal_code].filter(Boolean).join(", ")}</p>
        </div>
      </section>

      <table className="mb-4 w-full border-collapse">
        <thead>
          <tr className="bg-black/5 text-start">
            {[L.item, L.qty, L.price, L.discount, L.rate, L.vatAmount, L.lineTotal].map((p) => (
              <th key={p[0]} scope="col" className={`${cell} text-start`}><Label pair={p} /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {invoice.lines.map((l) => (
            <tr key={l.position}>
              <td className={cell}>{l.description}</td>
              <td className={`${cell} font-mono`} dir="ltr">{l.quantity}</td>
              <td className={`${cell} font-mono`} dir="ltr">{l.unit_price}</td>
              <td className={`${cell} font-mono`} dir="ltr">{l.discount}</td>
              <td className={`${cell} font-mono`} dir="ltr">{l.vat_rate}</td>
              <td className={`${cell} font-mono`} dir="ltr">{amount(l.vat_amount)}</td>
              <td className={`${cell} font-mono`} dir="ltr">{amount(l.total_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <dl className="ms-auto grid max-w-sm grid-cols-[1fr_auto] gap-x-4 gap-y-1">
        <dt><Label pair={L.beforeVat} /></dt><dd dir="ltr" className="font-mono">{amount(invoice.totals.tax_exclusive)}</dd>
        <dt><Label pair={L.totalVat} /></dt><dd dir="ltr" className="font-mono">{amount(invoice.totals.tax_total)}</dd>
        <dt className="border-t border-black/30 pt-1"><Label pair={L.total} /></dt>
        <dd dir="ltr" className="border-t border-black/30 pt-1 font-mono font-bold">{invoice.currency} {amount(invoice.totals.tax_inclusive)}</dd>
      </dl>
    </article>
  );
}

/** Print only the invoice, not the workspace around it. */
export const PRINT_CSS = `
@media print {
  body * { visibility: hidden !important; }
  .einvoice-print, .einvoice-print * { visibility: visible !important; }
  .einvoice-print { position: absolute; inset: 0; margin: 0; max-width: none; }
  @page { size: A4; margin: 12mm; }
}`;
