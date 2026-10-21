"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { display } from "./money";
import { QrImage } from "./QrImage";
import { StatusBadge, useLabels } from "./status";
import type { AuthorityMessage, Invoice } from "./types";

function download(filename: string, text: string, type = "application/xml") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function Messages({ title, rows, tone }: { title: string; rows?: AuthorityMessage[]; tone: "bad" | "waiting" | "neutral" }) {
  if (!rows?.length) return null;
  return (
    <div className="mb-3">
      <h3 className="mb-1 text-sm font-medium">{title}</h3>
      <ul className="flex flex-col gap-1 text-sm">
        {rows.map((m, i) => (
          <li key={i} className="flex flex-wrap items-start gap-2">
            {m.code ? <Badge tone={tone}>{m.code}</Badge> : null}
            <span>{m.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const pre = "max-w-full overflow-x-auto break-all rounded-lg bg-[color:var(--fb-v2-raised)] p-2 text-xs v2-mono";

export function InvoiceView({ orgId, orgSlug, invoice, canIssue, userId, onChange }: { orgId: string; orgSlug: string; invoice: Invoice; canIssue: boolean; userId: string | null; onChange: (inv: Invoice) => void }) {
  const tr = useTr();
  const labels = useLabels();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [signature, setSignature] = useState("");
  const authority = labels.authority(invoice.country);
  const base = `/orgs/${orgId}/einvoices/${invoice.id}`;
  const places = invoice.country === "SA" ? 2 : 5;
  const money = (v: string) => (invoice.country === "SA" ? v : display(Number(v).toFixed(places)));

  async function act<T>(key: string, fn: () => Promise<T>, ok: string, pick: (r: T) => Invoice) {
    setBusy(key);
    setMessage(null);
    try {
      const result = await fn();
      onChange(pick(result));
      setMessage({ kind: "ok", text: ok });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  async function downloadXml(cleared: boolean) {
    try {
      const r = await api.get<{ filename: string; xml: string }>(`${base}/xml`, cleared ? { cleared: "1" } : undefined);
      download(r.filename, r.xml);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function downloadToSign() {
    try {
      const r = await api.get<{ filename: string; canonical: string; sha256: string }>(`${base}/eta-document`);
      download(r.filename, r.canonical, "text/plain;charset=utf-8");
      setMessage({ kind: "ok", text: tr("Downloaded. Sign this text with your token (SHA-256 {hash}).", { hash: r.sha256.slice(0, 16) + "…" }) });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const response = invoice.authority_response || {};
  const errorTextValue = typeof response.error === "string" ? response.error : response.error?.message;
  const canSend = canIssue && (invoice.status === "ready" || invoice.status === "error") && !invoice.waiting_approval;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={invoice.status} waiting={invoice.waiting_approval} simulated={invoice.simulated} />
        <span className="text-sm text-[color:var(--fb-v2-text-muted)]">
          {labels.country(invoice.country)} · {labels.type(invoice.invoice_type)} · {labels.kind(invoice.kind)}
          {invoice.authority_status ? ` · ${authority}: ${invoice.authority_status}` : ""}
        </span>
      </div>

      {invoice.waiting_approval && invoice.approval ? (
        <div role="status" className="rounded-xl p-3 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]">
          <p className="mb-2 text-sm"><span className="font-medium text-[color:var(--fb-v2-waiting)]">{invoice.approval.user === userId ? tr("Waiting for your approval") : tr("Waiting for approval")}</span> · {invoice.approval.summary}</p>
          {invoice.approval.user === userId && canIssue ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="waiting" disabled={!!busy} onClick={() => act("approve", () => api.post<{ invoice: Invoice }>(`${base}/approval/approve`), tr("Approved. The answer is below."), (r) => r.invoice)}>
              {busy === "approve" ? tr("Sending…") : tr("Approve and send")}
            </Button>
            <Button variant="outline" disabled={!!busy} onClick={() => act("reject", () => api.post<{ invoice: Invoice }>(`${base}/approval/reject`), tr("Not sent."), (r) => r.invoice)}>
              {tr("Reject")}
            </Button>
          </div>
          ) : (
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("The person who asked to send it approves it in their approvals.")}</p>
          )}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {canIssue && invoice.status === "draft" ? (
          <>
            <Button asChild variant="outline"><Link href={`/w/${orgSlug}/einvoices/${invoice.id}?edit=1`}>{tr("Edit")}</Link></Button>
            <Button disabled={!!busy} onClick={() => act("prepare", () => api.post<Invoice>(`${base}/prepare`), invoice.country === "SA" ? tr("Signed and stamped. Ready to send.") : tr("Prepared. Ready to sign and send."), (r) => r)}>
              {invoice.country === "SA" ? tr("Sign and stamp") : tr("Prepare for the ETA")}
            </Button>
          </>
        ) : null}
        {canSend ? (
          <Button disabled={!!busy || !!invoice.blocker} onClick={() => act("submit", () => api.post<{ invoice: Invoice }>(`${base}/submit`), tr("Waiting for approval. Nothing is sent until you approve."), (r) => r.invoice)}>
            {invoice.country === "SA" ? (invoice.invoice_type === "standard" ? tr("Send to ZATCA for clearance") : tr("Report to ZATCA")) : tr("Send to the ETA")}
          </Button>
        ) : null}
        {canIssue && invoice.status === "submitted" && invoice.country === "EG" ? (
          <Button variant="outline" disabled={!!busy} onClick={() => act("poll", () => api.post<Invoice>(`${base}/poll`), tr("Status checked."), (r) => r)}>
            {tr("Check status")}
          </Button>
        ) : null}
        {invoice.has_xml ? <Button variant="outline" onClick={() => downloadXml(false)}>{tr("Download XML")}</Button> : null}
        {invoice.has_cleared_xml ? <Button variant="outline" onClick={() => downloadXml(true)}>{tr("Download cleared XML")}</Button> : null}
        {invoice.status !== "draft" ? <Button asChild variant="outline"><Link href={`/w/${orgSlug}/einvoices/${invoice.id}/print`}>{tr("Print view")}</Link></Button> : null}
        {canIssue && (invoice.status === "rejected" || invoice.status === "error" || invoice.status === "accepted") ? (
          <Button variant="ghost" disabled={!!busy} onClick={() => act("copy", () => api.post<Invoice>(`${base}/copy`), tr("Copied to a new draft."), (r) => r)}>
            {tr("Copy to a new draft")}
          </Button>
        ) : null}
      </div>
      {invoice.blocker && canSend ? <Notice>{tr(invoice.blocker)}</Notice> : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      {invoice.country === "EG" && canIssue && (invoice.status === "ready" || invoice.status === "error") && invoice.signer_mode === "manual" ? (
        <Section title={tr("Sign with your token")}>
          <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("The ETA needs a CAdES-BES signature made with your company's USB token. FloBrain never signs for you. Download the text, sign it with your signing tool, then paste the Base64 signature.")}
          </p>
          <div className="mb-3 flex flex-wrap gap-2">
            <Button variant="outline" onClick={downloadToSign}>{tr("Download the text to sign")}</Button>
            {invoice.eta_signed ? <Badge tone="good">{tr("Signature added")}</Badge> : null}
          </div>
          <Field label={tr("Signature (Base64)")}>
            <textarea className={`${pre} min-h-24 w-full`} value={signature} onChange={(e) => setSignature(e.target.value)} dir="ltr" />
          </Field>
          <Button variant="outline" disabled={!signature.trim() || !!busy} onClick={() => act("sign", () => api.post<Invoice>(`${base}/signature`, { signature }), tr("Signature added."), (r) => r)}>
            {tr("Add signature")}
          </Button>
        </Section>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
        <div>
          <Section title={tr("Parties")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="text-sm">
                <h3 className="mb-1 font-medium">{tr("Seller")}</h3>
                <p>{invoice.seller.name}{invoice.seller.name_ar ? <span lang="ar" dir="rtl"> · {invoice.seller.name_ar}</span> : null}</p>
                <p className="text-[color:var(--fb-v2-text-muted)]"><span dir="ltr">{invoice.seller.tax_number}</span></p>
                <p className="text-[color:var(--fb-v2-text-muted)]">{invoice.seller.address}</p>
              </div>
              <div className="text-sm">
                <h3 className="mb-1 font-medium">{tr("Buyer")}</h3>
                <p>{invoice.buyer_name || tr("Consumer (not named)")}</p>
                {invoice.buyer_tax_number ? <p className="text-[color:var(--fb-v2-text-muted)]"><span dir="ltr">{invoice.buyer_tax_number}</span></p> : null}
                <p className="text-[color:var(--fb-v2-text-muted)]">{[invoice.buyer_building_number, invoice.buyer_street, invoice.buyer_district, invoice.buyer_city, invoice.buyer_region, invoice.buyer_postal_code].filter(Boolean).join(", ")}</p>
              </div>
            </div>
          </Section>
          <Section title={tr("Lines")}>
            <Rows>
              {invoice.lines.map((l) => (
                <Row key={l.position}>
                  <div className="min-w-0 flex-1 basis-56">
                    <p className="font-medium">{l.description}</p>
                    <p className="v2-mono text-xs text-[color:var(--fb-v2-text-muted)]">
                      {l.quantity} × {l.unit_price}{Number(l.discount) ? ` − ${l.discount}` : ""} · {l.vat_category} {l.vat_rate}%{l.item_code ? ` · ${l.item_type} ${l.item_code}` : ""}
                    </p>
                  </div>
                  <span className="v2-mono text-sm">{money(l.total_amount ?? "0")}</span>
                </Row>
              ))}
            </Rows>
            <dl className="v2-mono mt-3 grid max-w-sm grid-cols-2 gap-y-1 text-sm ms-auto">
              <dt className="text-[color:var(--fb-v2-text-muted)]">{tr("Before VAT")}</dt><dd className="text-end">{money(invoice.totals.tax_exclusive)}</dd>
              <dt className="text-[color:var(--fb-v2-text-muted)]">{tr("VAT")}</dt><dd className="text-end">{money(invoice.totals.tax_total)}</dd>
              <dt className="font-medium">{tr("Total")}</dt><dd className="text-end font-semibold">{invoice.currency} {money(invoice.totals.tax_inclusive)}</dd>
            </dl>
          </Section>
        </div>
        {invoice.qr ? (
          <aside className="flex flex-col items-center gap-2">
            <QrImage value={invoice.qr} label={tr("ZATCA QR code for invoice {number}", { number: invoice.number })} />
            <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Scan with the ZATCA VAT app")}</p>
          </aside>
        ) : null}
      </div>

      {invoice.status !== "draft" ? (
        <Section title={tr("Tax authority")}>
          {invoice.simulated ? <Notice>{tr("Demo: this answer was simulated. Nothing was sent to {authority}.", { authority })}</Notice> : null}
          {invoice.authority_response?.warnings ? <Notice>{tr("Accepted with warnings. Fix them on your next invoices.")}</Notice> : null}
          <Messages title={tr("Errors")} rows={invoice.authority_response?.errorMessages} tone="bad" />
          <Messages title={tr("Warnings")} rows={invoice.authority_response?.warningMessages} tone="waiting" />
          <Messages title={tr("Information")} rows={invoice.authority_response?.infoMessages} tone="neutral" />
          {invoice.authority_response?.rejected?.map((r, i) => (
            <Messages key={i} title={tr("Rejected by the ETA")} rows={[r.error, ...(r.error.details ?? [])]} tone="bad" />
          ))}
          {errorTextValue ? <Notice kind="error">{errorTextValue}</Notice> : null}
          <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
            {invoice.icv ? (<><dt className="text-[color:var(--fb-v2-text-muted)]">{tr("Invoice counter")}</dt><dd className="v2-mono">{invoice.icv}</dd></>) : null}
            {invoice.invoice_hash ? (<><dt className="text-[color:var(--fb-v2-text-muted)]">{tr("Invoice hash")}</dt><dd className="v2-mono break-all" dir="ltr">{invoice.invoice_hash}</dd></>) : null}
            {invoice.pih ? (<><dt className="text-[color:var(--fb-v2-text-muted)]">{tr("Previous invoice hash")}</dt><dd className="v2-mono break-all" dir="ltr">{invoice.pih}</dd></>) : null}
            {invoice.authority_uuid ? (<><dt className="text-[color:var(--fb-v2-text-muted)]">{tr("ETA document ID")}</dt><dd className="v2-mono break-all" dir="ltr">{invoice.authority_uuid}</dd></>) : null}
            {invoice.authority_submission ? (<><dt className="text-[color:var(--fb-v2-text-muted)]">{tr("ETA submission ID")}</dt><dd className="v2-mono break-all" dir="ltr">{invoice.authority_submission}</dd></>) : null}
            {invoice.eta_signature_simulated ? (<><dt className="text-[color:var(--fb-v2-text-muted)]">{tr("Signature")}</dt><dd>{tr("Demo stand-in, not a real signature")}</dd></>) : null}
          </dl>
          {invoice.events.length ? (
            <ul className="mt-3 flex flex-col gap-1 text-xs text-[color:var(--fb-v2-text-muted)]">
              {invoice.events.map((e, i) => (
                <li key={i}>{when(e.at)} · {e.action} · {e.outcome}{e.http_status ? ` (${e.http_status})` : ""}{e.simulated ? ` · ${tr("Simulated")}` : ""}</li>
              ))}
            </ul>
          ) : null}
        </Section>
      ) : null}
    </div>
  );
}
