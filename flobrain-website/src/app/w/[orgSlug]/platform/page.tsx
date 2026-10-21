"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Org = { id: string; name: string; slug: string; active_members: number; subscription: { plan: string; status: string } | null; flags: Record<string, boolean> };
type Plan = {
  id: string;
  code: string;
  name: string;
  price_cents: number;
  currency: string;
  interval: string;
  entitlements: { flags?: string[]; limits?: Record<string, number> };
  is_public: boolean;
  stripe_price_id?: string;
};
const EMPTY_PLAN = { code: "", name: "", price: "", interval: "month", flags: "", seats: "", renders: "", stripe_price_id: "", is_public: true };
type Session = { id: string; org: string; user: { email: string }; admin: { email: string }; reason: string; expires_at: string; live: boolean };

export default function PlatformPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const [q, setQ] = useState("");
  const orgs = useOrgData<Org[]>(orgId, `/platform/orgs${q ? `?q=${encodeURIComponent(q)}` : ""}`, { orgScoped: false, list: true });
  const sessions = useOrgData<Session[]>(orgId, "/platform/impersonations", { orgScoped: false, list: true });
  const plans = useOrgData<Plan[]>(orgId, "/platform/plans", { orgScoped: false, list: true });
  const [form, setForm] = useState({ org: "", user: "", reason: "", minutes: "15" });
  const [onboard, setOnboard] = useState({ name: "", slug: "", owner_email: "" });
  const [plan, setPlan] = useState(EMPTY_PLAN);
  const [assign, setAssign] = useState<Record<string, { plan: string; seats: string }>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  if (!access?.is_platform_admin) return <Notice>{tr("This console is for FloBrain staff.")}</Notice>;

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      orgs.reload();
      sessions.reload();
      plans.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-5xl">
      <PageHeader title={tr("Platform console")} intro={tr("Every change here is written to the customer's audit log.")} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Section title={tr("Onboard an organization")}>
        <form
          className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.post("/platform/orgs", onboard), tr("Created {name}. The owner got an email.", { name: onboard.name }));
            setOnboard({ name: "", slug: "", owner_email: "" });
          }}
        >
          <div className="grid gap-x-4 sm:grid-cols-3">
            <Field label={tr("Name")}>
              <input className="v2-input" required minLength={2} value={onboard.name} onChange={(e) => setOnboard({ ...onboard, name: e.target.value })} />
            </Field>
            <Field label={tr("Address")} hint={tr("Lowercase letters, digits and dashes.")}>
              <input className="v2-input" dir="ltr" required pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]" value={onboard.slug} onChange={(e) => setOnboard({ ...onboard, slug: e.target.value.toLowerCase() })} />
            </Field>
            <Field label={tr("Owner's email")}>
              <input className="v2-input" type="email" required value={onboard.owner_email} onChange={(e) => setOnboard({ ...onboard, owner_email: e.target.value })} />
            </Field>
          </div>
          <Button type="submit">{tr("Create organization")}</Button>
        </form>
      </Section>

      <Section title={tr("Plans")}>
        <form
          className="mb-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            const limits: Record<string, number> = {};
            if (plan.seats) limits.seats = Number(plan.seats);
            if (plan.renders) limits.renders_per_month = Number(plan.renders);
            act(
              () =>
                api.post("/platform/plans", {
                  code: plan.code,
                  name: plan.name,
                  price_cents: Math.round(Number(plan.price || 0) * 100),
                  interval: plan.interval,
                  entitlements: { flags: plan.flags.split(",").map((f) => f.trim()).filter(Boolean), limits },
                  stripe_price_id: plan.stripe_price_id,
                  is_public: plan.is_public,
                }),
              tr("Plan {code} saved.", { code: plan.code }),
            );
          }}
        >
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Saving a code that exists updates that plan. Orgs on it get the new features at once.")}</p>
          <div className="grid gap-x-4 sm:grid-cols-3">
            <Field label={tr("Code")}>
              <input className="v2-input" dir="ltr" required value={plan.code} onChange={(e) => setPlan({ ...plan, code: e.target.value })} />
            </Field>
            <Field label={tr("Name")}>
              <input className="v2-input" value={plan.name} onChange={(e) => setPlan({ ...plan, name: e.target.value })} />
            </Field>
            <Field label={tr("Price per seat (USD)")}>
              <input className="v2-input" type="number" min={0} step="0.01" value={plan.price} onChange={(e) => setPlan({ ...plan, price: e.target.value })} />
            </Field>
            <Field label={tr("Billed")}>
              <select className="v2-input" value={plan.interval} onChange={(e) => setPlan({ ...plan, interval: e.target.value })}>
                <option value="month">{tr("Monthly")}</option>
                <option value="year">{tr("Yearly")}</option>
              </select>
            </Field>
            <Field label={tr("Seat limit")}>
              <input className="v2-input" type="number" min={0} value={plan.seats} onChange={(e) => setPlan({ ...plan, seats: e.target.value })} />
            </Field>
            <Field label={tr("Renders per month")}>
              <input className="v2-input" type="number" min={0} value={plan.renders} onChange={(e) => setPlan({ ...plan, renders: e.target.value })} />
            </Field>
          </div>
          <Field label={tr("Features (flags, comma separated)")}>
            <input className="v2-input" dir="ltr" value={plan.flags} onChange={(e) => setPlan({ ...plan, flags: e.target.value })} placeholder="buddies, memory_search, content_studio" />
          </Field>
          <Field label={tr("Stripe price ID")}>
            <input className="v2-input" dir="ltr" value={plan.stripe_price_id} onChange={(e) => setPlan({ ...plan, stripe_price_id: e.target.value })} placeholder="price_…" />
          </Field>
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={plan.is_public} onChange={(e) => setPlan({ ...plan, is_public: e.target.checked })} />
            {tr("Customers can choose it at checkout")}
          </label>
          <Button type="submit">{tr("Save plan")}</Button>
        </form>
        <ScreenBody state={plans.state} error={plans.error} emptyLabel={tr("No plans yet.")} onRetry={plans.reload}>
          <Rows>
            {rowsOf<Plan>(plans.data).map((p) => (
              <Row key={p.code}>
                <div className="min-w-0">
                  <p className="font-medium">
                    {p.name} <code className="text-sm text-[color:var(--fb-v2-text-muted)]">{p.code}</code> {p.is_public ? <Badge tone="good">{tr("Public")}</Badge> : <Badge>{tr("Hidden")}</Badge>}
                  </p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {(p.price_cents / 100).toFixed(2)} {p.currency} / {p.interval === "year" ? tr("year") : tr("month")}. {(p.entitlements.flags ?? []).join(", ") || tr("No features")}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  onClick={() =>
                    setPlan({
                      code: p.code,
                      name: p.name,
                      price: (p.price_cents / 100).toString(),
                      interval: p.interval,
                      flags: (p.entitlements.flags ?? []).join(", "),
                      seats: p.entitlements.limits?.seats?.toString() ?? "",
                      renders: p.entitlements.limits?.renders_per_month?.toString() ?? "",
                      stripe_price_id: p.stripe_price_id ?? "",
                      is_public: p.is_public,
                    })
                  }
                >
                  {tr("Edit")}
                </Button>
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>

      <Section
        title={tr("Organizations")}
        aside={<input className="v2-input w-64" placeholder={tr("Search by name")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={tr("Search organizations")} />}
      >
        <ScreenBody state={orgs.state} error={orgs.error} emptyLabel={tr("No organizations match.")} onRetry={orgs.reload}>
          <Rows>
            {rowsOf<Org>(orgs.data).map((o) => (
              <Row key={o.id} className="items-start">
                <div className="min-w-0">
                  <p className="font-medium">
                    {o.name} <span className="text-sm text-[color:var(--fb-v2-text-muted)]">/{o.slug}</span>
                  </p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {tr("{n} active.", { n: o.active_members })} {o.subscription ? `${o.subscription.plan} (${o.subscription.status})` : tr("No plan")}.
                  </p>
                  <form
                    className="mt-2 flex flex-wrap items-center gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const choice = assign[o.id];
                      if (!choice?.plan) return;
                      act(
                        () => api.put(`/platform/orgs/${o.id}/subscription`, { plan: choice.plan, ...(choice.seats ? { seats: Number(choice.seats) } : {}) }),
                        tr("{org} is on {plan}.", { org: o.name, plan: choice.plan }),
                      );
                    }}
                  >
                    <select
                      className="v2-input w-40 py-1"
                      aria-label={tr("Plan for {org}", { org: o.name })}
                      value={assign[o.id]?.plan ?? o.subscription?.plan ?? ""}
                      onChange={(e) => setAssign({ ...assign, [o.id]: { plan: e.target.value, seats: assign[o.id]?.seats ?? "" } })}
                    >
                      <option value="">{tr("No plan")}</option>
                      {rowsOf<Plan>(plans.data).map((p) => (
                        <option key={p.code} value={p.code}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                    <input
                      className="v2-input w-24 py-1"
                      type="number"
                      min={1}
                      placeholder={tr("Seats")}
                      aria-label={tr("Seats for {org}", { org: o.name })}
                      value={assign[o.id]?.seats ?? ""}
                      onChange={(e) => setAssign({ ...assign, [o.id]: { plan: assign[o.id]?.plan ?? o.subscription?.plan ?? "", seats: e.target.value } })}
                    />
                    <Button type="submit" variant="outline" disabled={!assign[o.id]?.plan}>
                      {tr("Set plan")}
                    </Button>
                  </form>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {Object.entries(o.flags).map(([key, on]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => act(() => api.put(`/platform/orgs/${o.id}/flags`, { flags: { [key]: !on } }), on ? tr("{flag} off for {org}.", { flag: key, org: o.name }) : tr("{flag} on for {org}.", { flag: key, org: o.name }))}
                      >
                        <Badge tone={on ? "accent" : "neutral"}>{key}</Badge>
                      </button>
                    ))}
                  </div>
                </div>
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>

      <Section title={tr("View as a member (read-only)")}>
        <form
          className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.post("/platform/impersonations", { ...form, minutes: Number(form.minutes) }), tr("Session started. The person and their admins were notified."));
          }}
        >
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label={tr("Organization ID")}>
              <input className="v2-input" required value={form.org} onChange={(e) => setForm({ ...form, org: e.target.value })} />
            </Field>
            <Field label={tr("Member's user ID")}>
              <input className="v2-input" required value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} />
            </Field>
          </div>
          <Field label={tr("Reason")} hint={tr("The customer sees this. Include the ticket number.")}>
            <input className="v2-input" required minLength={10} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </Field>
          <Field label={tr("duration|For")}>
            <select className="v2-input w-40" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })}>
              <option value="15">{tr("15 minutes")}</option>
              <option value="30">{tr("30 minutes")}</option>
              <option value="60">{tr("1 hour")}</option>
            </select>
          </Field>
          <Button type="submit">{tr("Start session")}</Button>
        </form>
        <ScreenBody state={sessions.state} error={sessions.error} emptyLabel={tr("No sessions yet.")} onRetry={sessions.reload}>
          <Rows>
            {rowsOf<Session>(sessions.data).map((s) => (
              <Row key={s.id}>
                <div>
                  <p className="text-sm">
                    {tr("{admin} as {user}: {reason}", { admin: s.admin.email, user: s.user.email, reason: s.reason })}
                  </p>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Until {date}", { date: when(s.expires_at) })}</p>
                </div>
                {s.live ? (
                  <Button variant="danger" onClick={() => act(() => api.post(`/platform/impersonations/${s.id}/end`), tr("Ended."))}>
                    {tr("End")}
                  </Button>
                ) : (
                  <Badge>{tr("Ended")}</Badge>
                )}
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>
    </div>
  );
}
