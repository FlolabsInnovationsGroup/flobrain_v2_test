"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { InvoiceForm } from "@/components/v2/einvoice/InvoiceForm";
import type { Meta } from "@/components/v2/einvoice/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

export default function NewInvoicePage() {
  const tr = useTr();
  const router = useRouter();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId, access } = useAccess();
  const meta = useOrgData<Meta>(orgId, "/einvoice/meta");
  const allowed = has(access, "einvoice.issue");
  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("New e-invoice")}
        intro={tr("It stays a draft until you sign and send it.")}
        action={<Link className="text-sm underline-offset-2 hover:underline" href={`/w/${orgSlug}/einvoices`}>{tr("Back to e-invoices")}</Link>}
      />
      <ScreenBody state={access && !allowed ? "no-access" : meta.state} error={meta.error} onRetry={meta.reload}>
        {orgId ? <InvoiceForm orgId={orgId} meta={meta.data} invoice={null} onSaved={(inv) => router.push(`/w/${orgSlug}/einvoices/${inv.id}`)} /> : null}
      </ScreenBody>
    </div>
  );
}
