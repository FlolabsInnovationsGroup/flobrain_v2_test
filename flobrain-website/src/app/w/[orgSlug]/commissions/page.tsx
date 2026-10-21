"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Lead = { id: string; owner: { id: string; name: string }; project_or_product: string; contact_name: string; stage: string; estimated_value: string | null };
type Commission = { id: string; lead_name: string; user: { name: string }; amount: string; currency: string; status: string };
type Summary = { earned: string; pending: string; referrals_sent: number; won: number; conversion_rate: number | null };

const STAGES: [string, string][] = [
  ["contacted", "Contacted"],
  ["meeting_1", "Meeting 1"],
  ["in_progress", "In progress"],
  ["won", "Won"],
  ["lost", "Lost"],
];
const STATUSES = ["pending", "under_review", "approved", "rejected", "scheduled", "paid", "reversed"];

export default function CommissionsPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const manager = has(access, "commissions.manage");
  const leads = useOrgData<Lead[]>(orgId, "/leads");
  const commissions = useOrgData<Commission[]>(orgId, "/commissions");
  const summary = useOrgData<Summary>(orgId, "/commissions/summary");
  const [form, setForm] = useState({ project: "", contact: "", value: "" });
  const [record, setRecord] = useState<{ lead: string; amount: string; currency: string }>({ lead: "", amount: "", currency: "USD" });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      leads.reload();
      commissions.reload();
      summary.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const rows = rowsOf<Lead>(leads.data);
  return (
    <div className="max-w-6xl">
      <PageHeader title={tr("Leads and commission")} intro={tr("Bring in a lead, move it through the pipeline, and see what you've earned. Only admins record and change commissions.")} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {summary.data ? (
        <div className="mb-8 grid gap-3 sm:grid-cols-4">
          {[
            ["Earned", summary.data.earned],
            ["Pending", summary.data.pending],
            ["Referrals sent", String(summary.data.referrals_sent)],
            ["Conversion", summary.data.conversion_rate === null ? tr("No leads yet") : `${Math.round(summary.data.conversion_rate * 100)}%`],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr(label)}</p>
              <p className="mt-1 text-xl font-semibold">{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      <Section title={tr("Pipeline")}>
        <form
          className="mb-4 grid gap-x-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 sm:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.post(`/orgs/${orgId}/leads`, { project_or_product: form.project, contact_name: form.contact, estimated_value: form.value || null }), tr("Lead added."));
          }}
        >
          <Field label={tr("Project or product")}>
            <input className="v2-input" required value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} />
          </Field>
          <Field label={tr("Contact")}>
            <input className="v2-input" required value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} />
          </Field>
          <Field label={tr("Estimated value")}>
            <input className="v2-input" inputMode="decimal" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          </Field>
          <div className="flex items-center">
            <Button type="submit">{tr("Add lead")}</Button>
          </div>
        </form>
        <ScreenBody state={leads.state} error={leads.error} onRetry={leads.reload}>
          <div className="grid gap-3 md:grid-cols-5">
            {STAGES.map(([stage, label]) => (
              <section key={stage} aria-label={tr(label)} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-3">
                <h3 className="mb-2 text-sm font-semibold">
                  {tr(label)} <span className="text-[color:var(--fb-v2-text-muted)]">{rows.filter((l) => l.stage === stage).length}</span>
                </h3>
                <ul className="space-y-2">
                  {rows
                    .filter((l) => l.stage === stage)
                    .map((l) => (
                      <li key={l.id} className="rounded-lg p-2 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                        <p className="font-medium">{l.contact_name}</p>
                        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                          {l.project_or_product}
                          {l.estimated_value ? `, ${l.estimated_value}` : ""}
                          {manager ? `. ${tr("By {name}", { name: l.owner.name })}` : ""}
                        </p>
                        <select
                          className="v2-input mt-2 py-1 text-xs"
                          aria-label={tr("Stage for {name}", { name: l.contact_name })}
                          value={l.stage}
                          onChange={(e) => act(() => api.patch(`/orgs/${orgId}/leads/${l.id}`, { stage: e.target.value }), tr("Moved."))}
                        >
                          {STAGES.map(([k, lab]) => (
                            <option key={k} value={k}>
                              {tr(lab)}
                            </option>
                          ))}
                        </select>
                      </li>
                    ))}
                </ul>
              </section>
            ))}
          </div>
        </ScreenBody>
      </Section>

      <Section title={tr("Commissions")}>
        {manager ? (
          <form
            className="mb-4 flex flex-wrap items-end gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api.post(`/orgs/${orgId}/commissions`, record), tr("Commission recorded."));
            }}
          >
            <label className="text-sm">
              <span className="mb-1 block font-medium">{tr("Lead")}</span>
              <select className="v2-input w-56" required value={record.lead} onChange={(e) => setRecord({ ...record, lead: e.target.value })}>
                <option value="">{tr("Choose a won lead")}</option>
                {rows
                  .filter((l) => l.stage === "won")
                  .map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.contact_name} ({l.owner.name})
                    </option>
                  ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">{tr("Amount")}</span>
              <input className="v2-input w-32" required inputMode="decimal" value={record.amount} onChange={(e) => setRecord({ ...record, amount: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">{tr("Currency")}</span>
              <input className="v2-input w-20" maxLength={3} value={record.currency} onChange={(e) => setRecord({ ...record, currency: e.target.value.toUpperCase() })} />
            </label>
            <Button type="submit">{tr("Record")}</Button>
          </form>
        ) : null}
        <ScreenBody state={commissions.state} error={commissions.error} emptyLabel={tr("No commissions yet.")} onRetry={commissions.reload}>
          <Rows>
            {rowsOf<Commission>(commissions.data).map((c) => (
              <Row key={c.id}>
                <div>
                  <p className="font-medium">
                    {tr("{amount} {currency} for {name}", { amount: c.amount, currency: c.currency, name: c.user.name })}
                  </p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Lead: {name}", { name: c.lead_name })}</p>
                </div>
                {manager ? (
                  <select
                    className="v2-input w-40"
                    aria-label={tr("Status")}
                    value={c.status}
                    onChange={(e) => act(() => api.patch(`/orgs/${orgId}/commissions/${c.id}`, { status: e.target.value }), tr("Status changed and logged."))}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {tr(s.replace("_", " "))}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Badge tone={["approved", "scheduled", "paid"].includes(c.status) ? "good" : c.status === "pending" ? "waiting" : "neutral"}>
                    {tr(c.status.replace("_", " "))}
                  </Badge>
                )}
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>
    </div>
  );
}
