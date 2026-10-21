"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { format, totals } from "./money";
import type { Country, Invoice, Line, Meta } from "./types";

const input =
  "w-full rounded-lg bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]";

type Form = Record<string, string>;

const BUYER_KEYS = [
  "buyer_name", "buyer_tax_number", "buyer_registration_scheme", "buyer_registration_id", "buyer_street", "buyer_building_number",
  "buyer_district", "buyer_city", "buyer_region", "buyer_postal_code", "buyer_country",
] as const;

function emptyLine(country: Country): Line {
  return country === "SA"
    ? { description: "", quantity: "1", unit_price: "", discount: "0", vat_category: "S", vat_rate: "15", exemption_code: "", exemption_reason: "", unit_code: "PCE" }
    : { description: "", quantity: "1", unit_price: "", discount: "0", vat_category: "V009", vat_rate: "14", item_type: "EGS", item_code: "", unit_code: "EA" };
}

function initialForm(invoice: Invoice | null, country: Country): Form {
  const form: Form = {
    country,
    invoice_type: invoice?.invoice_type ?? (country === "SA" ? "simplified" : "b2b"),
    kind: invoice?.kind ?? "invoice",
    number: invoice?.number ?? "",
    currency: invoice?.currency ?? (country === "SA" ? "SAR" : "EGP"),
    exchange_rate: invoice?.exchange_rate ?? "",
    supply_date: invoice?.supply_date ?? "",
    billing_reference: invoice?.billing_reference ?? "",
    adjustment_reason: invoice?.adjustment_reason ?? "",
    note: invoice?.note ?? "",
    payment_means: invoice?.payment_means ?? "10",
  };
  for (const key of BUYER_KEYS) form[key] = (invoice?.[key] as string | undefined) ?? (key === "buyer_country" ? country : "");
  return form;
}

/** Create or edit a draft. Totals update as you type; the server computes the final numbers. */
export function InvoiceForm({ orgId, meta, invoice, onSaved }: { orgId: string; meta: Meta | null; invoice: Invoice | null; onSaved: (inv: Invoice) => void }) {
  const tr = useTr();
  const [country, setCountry] = useState<Country>(invoice?.country ?? "SA");
  const [form, setForm] = useState<Form>(() => initialForm(invoice, invoice?.country ?? "SA"));
  const [lines, setLines] = useState<Line[]>(() => (invoice?.lines.length ? invoice.lines.map((l) => ({ ...l })) : [emptyLine(invoice?.country ?? "SA")]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const places = country === "SA" ? 2 : 5;
  const live = useMemo(() => totals(country, lines, form.currency !== "EGP" ? form.exchange_rate : null), [country, lines, form.currency, form.exchange_rate]);
  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }));
  const setLine = (i: number, key: keyof Line, value: string) => setLines((rows) => rows.map((row, n) => (n === i ? { ...row, [key]: value } : row)));
  const standard = country === "SA" && form.invoice_type === "standard";
  const business = country === "EG" && form.invoice_type === "b2b";

  function switchCountry(next: Country) {
    setCountry(next);
    setForm(initialForm(null, next));
    setLines([emptyLine(next)]);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { ...form, lines };
    if (!form.number) delete body.number;
    if (!form.supply_date) body.supply_date = null;
    if (country === "SA" || form.currency === "EGP") delete body.exchange_rate;
    if (invoice) delete body.country;
    try {
      const saved = invoice
        ? await api.patch<Invoice>(`/orgs/${orgId}/einvoices/${invoice.id}`, body)
        : await api.post<Invoice>(`/orgs/${orgId}/einvoices`, body);
      onSaved(saved);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const categories = country === "SA" ? meta?.sa_categories ?? ["S", "Z", "E", "O"] : meta?.eg_subtypes ?? ["V009"];
  const categoryLabel = (c: string) =>
    c === "S" ? tr("S: standard rate") : c === "Z" ? tr("Z: zero rated") : c === "E" ? tr("E: exempt") : c === "O" ? tr("O: out of scope") : c === "V009" ? tr("V009: general sales") : c;

  return (
    <form onSubmit={save} className="flex flex-col gap-2" noValidate>
      <Section title={tr("Invoice")}>
        <div className="grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          {!invoice ? (
            <Field label={tr("Country")}>
              <select className={input} value={country} onChange={(e) => switchCountry(e.target.value as Country)}>
                <option value="SA">{tr("Saudi Arabia (ZATCA)")}</option>
                <option value="EG">{tr("Egypt (ETA)")}</option>
              </select>
            </Field>
          ) : null}
          <Field label={tr("Type")} hint={country === "SA" ? tr("Standard invoices are cleared by ZATCA before you send them. Simplified ones are reported within 24 hours.") : undefined}>
            <select className={input} value={form.invoice_type} onChange={(e) => set("invoice_type", e.target.value)}>
              {country === "SA" ? (
                <>
                  <option value="standard">{tr("Standard (B2B)")}</option>
                  <option value="simplified">{tr("Simplified (B2C)")}</option>
                </>
              ) : (
                <>
                  <option value="b2b">{tr("Business")}</option>
                  <option value="b2c">{tr("Consumer")}</option>
                </>
              )}
            </select>
          </Field>
          {country === "SA" ? (
            <Field label={tr("Document")}>
              <select className={input} value={form.kind} onChange={(e) => set("kind", e.target.value)}>
                <option value="invoice">{tr("Invoice")}</option>
                <option value="credit">{tr("Credit note")}</option>
                <option value="debit">{tr("Debit note")}</option>
              </select>
            </Field>
          ) : null}
          <Field label={tr("Invoice number")} hint={tr("Leave empty to number it for you.")}>
            <input className={input} value={form.number} onChange={(e) => set("number", e.target.value)} maxLength={50} dir="ltr" />
          </Field>
          {country === "EG" ? (
            <Field label={tr("Currency")}>
              <input className={input} value={form.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} maxLength={3} dir="ltr" />
            </Field>
          ) : null}
          {country === "EG" && form.currency !== "EGP" ? (
            <Field label={tr("Exchange rate (EGP per unit)")}>
              <input className={input} value={form.exchange_rate} onChange={(e) => set("exchange_rate", e.target.value)} inputMode="decimal" dir="ltr" />
            </Field>
          ) : null}
          {country === "SA" ? (
            <Field label={tr("Supply date")} hint={standard ? tr("Required on standard invoices. Empty uses the issue date.") : undefined}>
              <input type="date" className={input} value={form.supply_date} onChange={(e) => set("supply_date", e.target.value)} />
            </Field>
          ) : null}
        </div>
        {country === "SA" && form.kind !== "invoice" ? (
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label={tr("Original invoice number")}>
              <input className={input} value={form.billing_reference} onChange={(e) => set("billing_reference", e.target.value)} maxLength={50} dir="ltr" />
            </Field>
            <Field label={tr("Reason for the note")}>
              <input className={input} value={form.adjustment_reason} onChange={(e) => set("adjustment_reason", e.target.value)} maxLength={300} />
            </Field>
          </div>
        ) : null}
      </Section>

      <Section title={tr("Buyer")}>
        <div className="grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={tr("Name")}>
            <input className={input} value={form.buyer_name} onChange={(e) => set("buyer_name", e.target.value)} maxLength={200} required={standard || business} />
          </Field>
          <Field label={country === "SA" ? tr("VAT number") : tr("Tax registration number or national ID")} hint={country === "SA" ? tr("15 digits, starts and ends with 3.") : undefined}>
            <input className={input} value={form.buyer_tax_number} onChange={(e) => set("buyer_tax_number", e.target.value)} maxLength={20} dir="ltr" inputMode="numeric" />
          </Field>
          {country === "SA" ? (
            <Field label={tr("Other ID (if no VAT number)")}>
              <div className="flex gap-2">
                <select className={`${input} w-28`} value={form.buyer_registration_scheme} onChange={(e) => set("buyer_registration_scheme", e.target.value)} aria-label={tr("ID type")}>
                  <option value="">{tr("None")}</option>
                  {["CRN", "NAT", "IQA", "PAS", "GCC", "TIN", "MOM", "MLS", "700", "SAG", "OTH"].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <input className={input} value={form.buyer_registration_id} onChange={(e) => set("buyer_registration_id", e.target.value)} maxLength={40} dir="ltr" aria-label={tr("ID number")} />
              </div>
            </Field>
          ) : null}
          <Field label={tr("Street")}>
            <input className={input} value={form.buyer_street} onChange={(e) => set("buyer_street", e.target.value)} maxLength={200} />
          </Field>
          <Field label={tr("Building number")}>
            <input className={input} value={form.buyer_building_number} onChange={(e) => set("buyer_building_number", e.target.value)} maxLength={20} dir="ltr" />
          </Field>
          {country === "SA" ? (
            <Field label={tr("District")}>
              <input className={input} value={form.buyer_district} onChange={(e) => set("buyer_district", e.target.value)} maxLength={120} />
            </Field>
          ) : (
            <Field label={tr("Governorate")}>
              <input className={input} value={form.buyer_region} onChange={(e) => set("buyer_region", e.target.value)} maxLength={120} />
            </Field>
          )}
          <Field label={tr("City")}>
            <input className={input} value={form.buyer_city} onChange={(e) => set("buyer_city", e.target.value)} maxLength={120} />
          </Field>
          <Field label={tr("Postal code")}>
            <input className={input} value={form.buyer_postal_code} onChange={(e) => set("buyer_postal_code", e.target.value)} maxLength={10} dir="ltr" />
          </Field>
          <Field label={tr("Country code")}>
            <input className={input} value={form.buyer_country} onChange={(e) => set("buyer_country", e.target.value.toUpperCase())} maxLength={2} dir="ltr" />
          </Field>
        </div>
      </Section>

      <Section title={tr("Lines")} aside={<Button type="button" variant="outline" onClick={() => setLines((rows) => [...rows, emptyLine(country)])}>{tr("Add a line")}</Button>}>
        <ol className="flex flex-col gap-3">
          {lines.map((line, i) => {
            const t = live.lines[i];
            return (
              <li key={i} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                <div className="grid gap-x-3 sm:grid-cols-2 lg:grid-cols-6">
                  <div className="lg:col-span-2">
                    <Field label={tr("Description")}>
                      <input className={input} value={line.description} onChange={(e) => setLine(i, "description", e.target.value)} maxLength={300} />
                    </Field>
                  </div>
                  <Field label={tr("Quantity")}>
                    <input className={input} value={line.quantity} onChange={(e) => setLine(i, "quantity", e.target.value)} inputMode="decimal" dir="ltr" />
                  </Field>
                  <Field label={tr("Unit price")}>
                    <input className={input} value={line.unit_price} onChange={(e) => setLine(i, "unit_price", e.target.value)} inputMode="decimal" dir="ltr" />
                  </Field>
                  <Field label={tr("Discount (amount)")}>
                    <input className={input} value={line.discount} onChange={(e) => setLine(i, "discount", e.target.value)} inputMode="decimal" dir="ltr" />
                  </Field>
                  <Field label={tr("VAT")}>
                    <div className="flex gap-2">
                      <select className={input} value={line.vat_category} onChange={(e) => setLine(i, "vat_category", e.target.value)} aria-label={tr("VAT category")}>
                        {categories.map((c) => (
                          <option key={c} value={c}>{categoryLabel(c)}</option>
                        ))}
                      </select>
                      <input className={`${input} w-20`} value={line.vat_rate} onChange={(e) => setLine(i, "vat_rate", e.target.value)} inputMode="decimal" dir="ltr" aria-label={tr("Rate %")} />
                    </div>
                  </Field>
                  {country === "SA" && line.vat_category !== "S" ? (
                    <>
                      <Field label={tr("Exemption code")} hint={tr("For example VATEX-SA-EDU or VATEX-SA-OOS.")}>
                        <input className={input} value={line.exemption_code ?? ""} onChange={(e) => setLine(i, "exemption_code", e.target.value.toUpperCase())} maxLength={30} dir="ltr" />
                      </Field>
                      <div className="lg:col-span-2">
                        <Field label={tr("Exemption reason")}>
                          <input className={input} value={line.exemption_reason ?? ""} onChange={(e) => setLine(i, "exemption_reason", e.target.value)} maxLength={200} />
                        </Field>
                      </div>
                    </>
                  ) : null}
                  {country === "EG" ? (
                    <>
                      <Field label={tr("Item code type")}>
                        <select className={input} value={line.item_type ?? "EGS"} onChange={(e) => setLine(i, "item_type", e.target.value)}>
                          <option value="EGS">EGS</option>
                          <option value="GS1">GS1</option>
                        </select>
                      </Field>
                      <div className="lg:col-span-2">
                        <Field label={tr("Item code")}>
                          <input className={input} value={line.item_code ?? ""} onChange={(e) => setLine(i, "item_code", e.target.value)} maxLength={100} dir="ltr" />
                        </Field>
                      </div>
                    </>
                  ) : null}
                  <Field label={tr("Unit")}>
                    <input className={input} value={line.unit_code ?? ""} onChange={(e) => setLine(i, "unit_code", e.target.value.toUpperCase())} maxLength={10} dir="ltr" />
                  </Field>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="v2-mono text-[color:var(--fb-v2-text-muted)]" aria-live="polite">
                    {t ? tr("Net {net} · VAT {vat} · Total {total}", { net: format(t.net, places), vat: format(t.vat, places), total: format(t.total, places) }) : tr("Check the numbers on this line")}
                  </span>
                  {lines.length > 1 ? (
                    <Button type="button" variant="ghost" onClick={() => setLines((rows) => rows.filter((_, n) => n !== i))}>
                      {tr("Remove line")}
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </Section>

      <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[color:var(--fb-v2-raised)] p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
        <dl className="v2-mono flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <div><dt className="inline text-[color:var(--fb-v2-text-muted)]">{tr("Before VAT")} </dt><dd className="inline">{format(live.net, places)}</dd></div>
          <div><dt className="inline text-[color:var(--fb-v2-text-muted)]">{tr("VAT")} </dt><dd className="inline">{format(live.vat, places)}</dd></div>
          <div><dt className="inline font-medium">{tr("Total")} </dt><dd className="inline font-semibold">{form.currency} {format(live.total, places)}</dd></div>
        </dl>
        <Button type="submit" disabled={busy || !live.valid}>
          {busy ? tr("Saving…") : invoice ? tr("Save draft") : tr("Create draft")}
        </Button>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </form>
  );
}
