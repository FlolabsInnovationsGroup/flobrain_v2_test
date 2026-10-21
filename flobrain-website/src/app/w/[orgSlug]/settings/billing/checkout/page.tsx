"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Plan = { code: string; name: string; price_cents: number; currency: string; interval: string; billing_unit?: string; included_seats?: number | null };
type Billing = { plan: Plan | null; status: string; seats: number | null; seats_used: number; current_period_end: string | null; checkout: string; can_manage: boolean; plans: Plan[] };

/**
 * Demo checkout and demo "billing portal". It only exists in demo mode (the API answers 404
 * otherwise). It sets the subscription directly: there is no payment and there are no card fields.
 */
export default function DemoCheckoutPage() {
  return (
    <Suspense>
      <DemoCheckout />
    </Suspense>
  );
}

function DemoCheckout() {
  const tr = useTr();
  const router = useRouter();
  const params = useSearchParams();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<Billing>(orgId, "/billing");
  const [seats, setSeats] = useState(params.get("seats") || "");
  const [message, setMessage] = useState("");
  const manage = params.get("manage") === "1";
  const plan = data?.plans.find((p) => p.code === params.get("plan")) ?? null;
  const back = `/w/${orgSlug}/settings/billing`;

  async function send(body: Record<string, unknown>) {
    setMessage("");
    try {
      await api.post(`/orgs/${orgId}/billing/demo`, body);
      router.push(`${back}?checkout=demo`);
    } catch (err) {
      setMessage(errorText(err));
    }
  }

  return (
    <div className="max-w-xl">
      <PageHeader title={manage ? tr("Demo billing portal") : tr("Demo checkout")} intro={tr("This is the demo. No payment is taken and no card is asked for. In a real workspace this step happens on Stripe.")} />
      <Badge tone="waiting">{tr("Demo")}</Badge>
      {message ? <Notice kind="error">{message}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data ? (
          data.checkout !== "demo" ? (
            <Notice>{tr("The demo checkout is only available in demo mode.")}</Notice>
          ) : !data.can_manage ? (
            <Notice>{tr("Only the owner can change the plan.")}</Notice>
          ) : manage ? (
            <div className="mt-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              <p className="font-semibold">{data.plan ? data.plan.name : tr("No plan yet")}</p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {data.seats ? tr("{n} seats.", { n: data.seats }) : ""} {data.current_period_end ? tr("Renews {date}", { date: when(data.current_period_end) }) : ""}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="outline" asChild>
                  <Link href={back}>{tr("Change plan")}</Link>
                </Button>
                {data.plan && data.status !== "canceled" ? (
                  <Button variant="danger" onClick={() => send({ action: "cancel" })}>
                    {tr("Cancel subscription (demo)")}
                  </Button>
                ) : null}
              </div>
            </div>
          ) : plan ? (
            <form
              className="mt-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
              onSubmit={(e) => {
                e.preventDefault();
                send({ action: "subscribe", plan: plan.code, seats: Number(seats) || 0, ...(params.get("interval") ? { interval: params.get("interval") } : {}) });
              }}
            >
              <p className="font-semibold">{plan.name}</p>
              <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
                {plan.billing_unit === "per_workspace"
                  ? tr("{price} for the workspace, up to {n} people", { price: (plan.price_cents / 100).toFixed(2) + " " + plan.currency, n: plan.included_seats ?? 0 })
                  : tr("{price} per seat, per month", { price: (plan.price_cents / 100).toFixed(2) + " " + plan.currency })}
              </p>
              {plan.billing_unit === "per_workspace" ? null : (
                <Field label={tr("Seats")}>
                  <input className="v2-input w-28" type="number" min={1} max={10000} value={seats} placeholder={String(Math.max(1, data.seats_used))} onChange={(e) => setSeats(e.target.value)} />
                </Field>
              )}
              <div className="flex gap-2">
                <Button type="submit">{tr("Confirm (demo, no payment)")}</Button>
                <Button variant="ghost" asChild>
                  <Link href={back}>{tr("Cancel")}</Link>
                </Button>
              </div>
            </form>
          ) : (
            <Notice>{tr("Pick a plan on the billing page first.")}</Notice>
          )
        ) : null}
      </ScreenBody>
    </div>
  );
}
