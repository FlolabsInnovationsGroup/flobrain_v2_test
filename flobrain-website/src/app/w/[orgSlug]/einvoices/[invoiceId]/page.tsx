"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { InvoiceForm } from "@/components/v2/einvoice/InvoiceForm";
import { InvoiceView } from "@/components/v2/einvoice/InvoiceView";
import type { Invoice, Meta } from "@/components/v2/einvoice/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

export default function InvoicePage() {
  return (
    <Suspense>
      <InvoiceScreen />
    </Suspense>
  );
}

function InvoiceScreen() {
  const tr = useTr();
  const router = useRouter();
  const params = useSearchParams();
  const { orgSlug, invoiceId } = useParams<{ orgSlug: string; invoiceId: string }>();
  const { orgId, access } = useAccess();
  const { data, state, error, reload, setData } = useOrgData<Invoice>(orgId, `/einvoices/${invoiceId}`);
  const meta = useOrgData<Meta>(orgId, params.get("edit") ? "/einvoice/meta" : null);
  const canIssue = has(access, "einvoice.issue");
  const editing = params.get("edit") === "1" && data?.status === "draft" && canIssue;

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={data ? tr("E-invoice {number}", { number: data.number }) : tr("E-invoice")}
        action={<Link className="text-sm underline-offset-2 hover:underline" href={`/w/${orgSlug}/einvoices`}>{tr("Back to e-invoices")}</Link>}
      />
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data && orgId ? (
          editing ? (
            <InvoiceForm
              key={data.id}
              orgId={orgId}
              meta={meta.data}
              invoice={data}
              onSaved={(inv) => {
                setData(inv);
                router.replace(`/w/${orgSlug}/einvoices/${inv.id}`);
              }}
            />
          ) : (
            <InvoiceView
              orgId={orgId}
              orgSlug={orgSlug}
              invoice={data}
              canIssue={canIssue}
              userId={access?.user_id ?? null}
              onChange={(inv) => (inv.id === data.id ? setData(inv) : router.push(`/w/${orgSlug}/einvoices/${inv.id}`))}
            />
          )
        ) : null}
      </ScreenBody>
    </div>
  );
}
