"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { PRINT_CSS, PrintInvoice } from "@/components/v2/einvoice/PrintInvoice";
import type { Invoice } from "@/components/v2/einvoice/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

export default function PrintPage() {
  const tr = useTr();
  const locale = useLocale();
  const { orgSlug, invoiceId } = useParams<{ orgSlug: string; invoiceId: string }>();
  const { orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<Invoice>(orgId, `/einvoices/${invoiceId}`);
  return (
    <div className="max-w-5xl">
      <style>{PRINT_CSS}</style>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Link className="text-sm underline-offset-2 hover:underline" href={`/w/${orgSlug}/einvoices/${invoiceId}`}>{tr("Back to the invoice")}</Link>
        <Button onClick={() => window.print()}>{tr("Print or save as PDF")}</Button>
      </div>
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data ? (
          <>
            {data.status === "ready" || data.status === "submitted" ? <Notice>{tr("Not accepted by the tax authority yet.")}</Notice> : null}
            <div className="overflow-x-auto rounded-xl ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
              <PrintInvoice invoice={data} dir={dirFor(locale)} />
            </div>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
