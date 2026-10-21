"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { display } from "@/components/v2/einvoice/money";
import { ResidencyPanel } from "@/components/v2/einvoice/ResidencyPanel";
import { EgyptSettings, SaudiSettings } from "@/components/v2/einvoice/SettingsPanel";
import { StatusBadge, useLabels } from "@/components/v2/einvoice/status";
import type { Invoice, InvoiceRow, Meta, Residency } from "@/components/v2/einvoice/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tab = "invoices" | "settings" | "residency";
const TABS: Tab[] = ["invoices", "settings", "residency"];
const select =
  "rounded-lg bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]";

export default function EInvoicesPage() {
  return (
    <Suspense>
      <EInvoicesScreen />
    </Suspense>
  );
}

function ImportForm({ orgId, onDone }: { orgId: string; onDone: (inv: Invoice) => void }) {
  const tr = useTr();
  const [provider, setProvider] = useState("odoo");
  const [country, setCountry] = useState("SA");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await api.post<Invoice>(`/orgs/${orgId}/einvoices/import`, { provider, country, ref }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Start a draft from an invoice in Odoo or Zoho Books, read through your connection. You review it before anything is signed or sent.")}</p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={tr("From")}>
          <select className={select} value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="odoo">Odoo</option>
            <option value="zoho">Zoho Books</option>
          </select>
        </Field>
        <Field label={tr("Country")}>
          <select className={select} value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="SA">{tr("Saudi Arabia (ZATCA)")}</option>
            <option value="EG">{tr("Egypt (ETA)")}</option>
          </select>
        </Field>
        <Field label={tr("Invoice number there")}>
          <input className={select} value={ref} onChange={(e) => setRef(e.target.value)} dir="ltr" maxLength={30} />
        </Field>
        <Button type="submit" className="mb-4" disabled={busy || !ref.trim()}>{busy ? tr("Importing…") : tr("Import as draft")}</Button>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </form>
  );
}

function EInvoicesScreen() {
  const tr = useTr();
  const labels = useLabels();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { orgId, access } = useAccess();
  const tab: Tab = TABS.includes(params.get("tab") as Tab) ? (params.get("tab") as Tab) : "invoices";
  const [country, setCountry] = useState("");
  const [status, setStatus] = useState("");
  const [importing, setImporting] = useState(false);
  const query = new URLSearchParams({ ...(country ? { country } : {}), ...(status ? { status } : {}) }).toString();
  const list = useOrgData<InvoiceRow[]>(orgId, tab === "invoices" ? `/einvoices${query ? `?${query}` : ""}` : null);
  const meta = useOrgData<Meta>(orgId, "/einvoice/meta");
  const residency = useOrgData<Residency>(orgId, tab === "residency" ? "/einvoice/residency" : null);
  const canIssue = has(access, "einvoice.issue");
  const canManage = has(access, "einvoice.manage");
  const rows = rowsOf<InvoiceRow>(list.data);
  const go = (next: Tab) => router.replace(`/w/${orgSlug}/einvoices${next === "invoices" ? "" : `?tab=${next}`}`);
  const waiting = rows.filter((r) => r.waiting_approval).length;

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("E-invoices")}
        intro={tr("Saudi ZATCA and Egyptian ETA e-invoices: totals worked out for you, signed and stamped, and sent to the tax authority only after you approve.")}
        action={
          canIssue && tab === "invoices" ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setImporting((v) => !v)} aria-expanded={importing}>{importing ? tr("Close") : tr("Import")}</Button>
              <Button asChild><Link href={`/w/${orgSlug}/einvoices/new`}>{tr("New invoice")}</Link></Button>
            </div>
          ) : null
        }
      />
      <div role="tablist" aria-label={tr("E-invoice sections")} className="mb-6 flex gap-1 overflow-x-auto border-b border-[color:var(--fb-v2-border)]">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => go(t)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] ${tab === t ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]"}`}
          >
            {t === "invoices" ? tr("Invoices") : t === "settings" ? tr("Settings") : tr("Data residency")}
          </button>
        ))}
      </div>

      {tab === "invoices" ? (
        <>
          {importing && orgId ? <ImportForm orgId={orgId} onDone={(inv) => router.push(`/w/${orgSlug}/einvoices/${inv.id}`)} /> : null}
          {waiting ? <Notice>{tr("{n} waiting for your approval before they go to the tax authority.", { n: waiting })}</Notice> : null}
          {meta.data && !meta.data.chain.ok ? <Notice kind="error">{tr("The Saudi invoice hash chain is broken at {number}. Contact support before sending more invoices.", { number: meta.data.chain.broken_at ?? "" })}</Notice> : null}
          <div className="mb-4 flex flex-wrap gap-3">
            <select className={select} value={country} onChange={(e) => setCountry(e.target.value)} aria-label={tr("Country")}>
              <option value="">{tr("All countries")}</option>
              <option value="SA">{tr("Saudi Arabia (ZATCA)")}</option>
              <option value="EG">{tr("Egypt (ETA)")}</option>
            </select>
            <select className={select} value={status} onChange={(e) => setStatus(e.target.value)} aria-label={tr("Status")}>
              <option value="">{tr("Any status")}</option>
              <option value="draft">{tr("Draft")}</option>
              <option value="ready">{tr("Ready to send")}</option>
              <option value="submitted">{tr("Submitted, checking")}</option>
              <option value="accepted">{tr("Accepted")}</option>
              <option value="rejected">{tr("Rejected")}</option>
              <option value="error">{tr("Error")}</option>
            </select>
          </div>
          <ScreenBody state={list.state === "ready" && !rows.length ? "empty" : list.state} error={list.error} emptyLabel={tr(canIssue ? "No e-invoices yet. Create one or import it from Odoo or Zoho." : "No e-invoices yet.")} onRetry={list.reload}>
            <Rows>
              {rows.map((r) => (
                <Row key={r.id}>
                  <div className="min-w-0 flex-1 basis-60">
                    <Link href={`/w/${orgSlug}/einvoices/${r.id}`} className="font-medium underline-offset-2 hover:underline focus-visible:underline">
                      <span dir="ltr">{r.number}</span>
                    </Link>
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {r.country === "SA" ? "ZATCA" : "ETA"} · {labels.type(r.invoice_type)}{r.kind !== "invoice" ? ` · ${labels.kind(r.kind)}` : ""} · {r.buyer_name || tr("Consumer (not named)")} · {when(r.issue_datetime)}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="v2-mono text-sm" dir="ltr">{r.currency} {display(r.total)}</span>
                    <StatusBadge status={r.status} waiting={r.waiting_approval} simulated={r.simulated} />
                  </div>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </>
      ) : null}

      {tab === "settings" && orgId ? (
        <ScreenBody state={meta.state} error={meta.error} onRetry={meta.reload}>
          {meta.data && canManage ? (
            <>
              <Section title={tr("Saudi Arabia (ZATCA)")}>
                <SaudiSettings key={`sa-${meta.data.profiles.SA?.updated_at ?? "new"}`} orgId={orgId} meta={meta.data} onChange={meta.reload} />
              </Section>
              <Section title={tr("Egypt (ETA)")}>
                <EgyptSettings key={`eg-${meta.data.profiles.EG?.updated_at ?? "new"}`} orgId={orgId} meta={meta.data} onChange={meta.reload} />
              </Section>
            </>
          ) : (
            <Notice>{tr("Only people who manage e-invoicing can change these settings.")}</Notice>
          )}
        </ScreenBody>
      ) : null}

      {tab === "residency" && orgId ? (
        <ScreenBody state={residency.state} error={residency.error} onRetry={residency.reload}>
          {residency.data ? <ResidencyPanel orgId={orgId} data={residency.data} onChange={(r) => residency.setData(r)} /> : null}
        </ScreenBody>
      ) : null}
    </div>
  );
}
