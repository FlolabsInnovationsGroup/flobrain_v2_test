"use client";

import { useState } from "react";

import { BudgetMeter, ON_EXCEED, type BudgetRow } from "@/components/v2/ai/BudgetMeter";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Field, Notice, PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Status = { results: BudgetRow[] };
type Listing = { downgrade_models: string[] };
type Option = { id: string; name?: string; username?: string };
type Form = {
  id: string | null;
  scope_type: "org" | "team" | "user";
  scope_id: string;
  cap_amount: string;
  currency: string;
  on_exceed: "block" | "downgrade" | "alert_only";
  downgrade_model: string;
  alert_threshold: string;
};

const EMPTY: Form = { id: null, scope_type: "team", scope_id: "", cap_amount: "", currency: "USD", on_exceed: "block", downgrade_model: "", alert_threshold: "80" };
const ORDER = { org: 0, team: 1, user: 2 } as const;

export function BudgetsScreen() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const manage = has(access, "budget.manage");
  const status = useOrgData<Status>(orgId, "/budgets/status");
  const listing = useOrgData<Listing>(orgId, manage ? "/budgets" : null);
  const teams = useOrgData<Option[]>(orgId, manage ? "/teams" : null);
  const members = useOrgData<{ results: Option[] }>(orgId, manage ? "/members?page_size=100" : null);
  const [form, setForm] = useState<Form | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const rows = [...rowsOf<BudgetRow>(status.data)].sort((a, b) => ORDER[a.scope_type] - ORDER[b.scope_type] || a.scope_name.localeCompare(b.scope_name));
  const hasOrg = rows.some((r) => r.scope_type === "org");
  const models = listing.data?.downgrade_models ?? [];

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      setForm(null);
      status.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  function save(event: React.FormEvent) {
    event.preventDefault();
    if (!form) return;
    const body = {
      cap_amount: form.cap_amount,
      currency: form.currency,
      on_exceed: form.on_exceed,
      downgrade_model: form.on_exceed === "downgrade" ? form.downgrade_model : "",
      alert_threshold: String(Number(form.alert_threshold) / 100),
    };
    if (form.id) {
      act(() => api.patch(`/orgs/${orgId}/budgets/${form.id}`, body), tr("Budget saved."));
    } else {
      act(
        () => api.post(`/orgs/${orgId}/budgets`, { ...body, scope_type: form.scope_type, scope_id: form.scope_type === "org" ? undefined : form.scope_id }),
        tr("Budget added."),
      );
    }
  }

  function edit(b: BudgetRow) {
    setForm({
      id: b.id,
      scope_type: b.scope_type,
      scope_id: b.scope_id ?? "",
      cap_amount: String(Number(b.cap_amount)),
      currency: b.currency,
      on_exceed: b.on_exceed,
      downgrade_model: b.downgrade_model ?? "",
      alert_threshold: String(Math.round(Number(b.alert_threshold) * 100)),
    });
  }

  const people = rowsOf<Option>(members.data);
  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("AI budgets")}
        intro={tr("Monthly limits for platform AI spend and GPU renders, for the organization, a team or one member. Members' own keys are never limited or switched.")}
        action={manage && !form ? <Button onClick={() => setForm({ ...EMPTY, scope_type: hasOrg ? "team" : "org" })}>{tr("Add a budget")}</Button> : undefined}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {form ? (
        <form onSubmit={save} className="mb-8 rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
          <div className="grid gap-x-4 sm:grid-cols-2">
            {!form.id ? (
              <>
                <Field label={tr("Applies to")}>
                  <select className="v2-input" value={form.scope_type} onChange={(e) => setForm({ ...form, scope_type: e.target.value as Form["scope_type"], scope_id: "" })}>
                    {!hasOrg ? <option value="org">{tr("The whole organization")}</option> : null}
                    <option value="team">{tr("A team")}</option>
                    <option value="user">{tr("One member")}</option>
                  </select>
                </Field>
                {form.scope_type === "team" ? (
                  <Field label={tr("Team")}>
                    <select className="v2-input" required value={form.scope_id} onChange={(e) => setForm({ ...form, scope_id: e.target.value })}>
                      <option value="">{tr("Pick a team")}</option>
                      {rowsOf<Option>(teams.data).map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                ) : form.scope_type === "user" ? (
                  <Field label={tr("Member")}>
                    <select className="v2-input" required value={form.scope_id} onChange={(e) => setForm({ ...form, scope_id: e.target.value })}>
                      <option value="">{tr("Pick a member")}</option>
                      {people.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.username || p.id.slice(0, 8)}
                        </option>
                      ))}
                    </select>
                  </Field>
                ) : (
                  <div />
                )}
              </>
            ) : null}
            <Field label={tr("Monthly limit")}>
              <div className="flex gap-2">
                <input className="v2-input" required inputMode="decimal" pattern="[0-9]+([.][0-9]{1,4})?" value={form.cap_amount} onChange={(e) => setForm({ ...form, cap_amount: e.target.value })} />
                <input className="v2-input w-24" aria-label={tr("Currency")} maxLength={3} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
              </div>
            </Field>
            <Field label={tr("Alert owners and admins at (%)")} hint={tr("Once a month, when spend reaches this share of the limit")}>
              <input className="v2-input" type="number" min={5} max={100} required value={form.alert_threshold} onChange={(e) => setForm({ ...form, alert_threshold: e.target.value })} />
            </Field>
            <Field label={tr("At 100%")}>
              <select className="v2-input" value={form.on_exceed} onChange={(e) => setForm({ ...form, on_exceed: e.target.value as Form["on_exceed"] })}>
                {Object.entries(ON_EXCEED).map(([k, label]) => (
                  <option key={k} value={k}>
                    {tr(label)}
                  </option>
                ))}
              </select>
            </Field>
            {form.on_exceed === "downgrade" ? (
              <Field label={tr("Cheaper model")} hint={tr("A platform model. Buddies and agents switch to it and say so.")}>
                <select className="v2-input" required value={form.downgrade_model} onChange={(e) => setForm({ ...form, downgrade_model: e.target.value })}>
                  <option value="">{models.length ? tr("Pick a model") : tr("No platform models are set up")}</option>
                  {models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="submit">{form.id ? tr("Save") : tr("Add budget")}</Button>
            <Button type="button" variant="ghost" onClick={() => setForm(null)}>
              {tr("Cancel")}
            </Button>
          </div>
        </form>
      ) : null}
      <ScreenBody state={status.state} error={status.error} onRetry={status.reload}>
        {rows.length === 0 ? (
          <Notice>{tr("No budgets yet. Without one, platform AI use is not limited.")}</Notice>
        ) : (
          (["org", "team", "user"] as const).map((scope) => {
            const items = rows.filter((r) => r.scope_type === scope);
            if (!items.length) return null;
            return (
              <Section key={scope} title={tr(scope === "org" ? "Organization" : scope === "team" ? "Teams" : "Members")}>
                <div className="grid gap-3 md:grid-cols-2">
                  {items.map((b) => (
                    <BudgetMeter
                      key={b.id}
                      budget={b}
                      actions={
                        manage ? (
                          <>
                            <Button variant="outline" onClick={() => edit(b)}>
                              {tr("Edit")}
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                if (window.confirm(tr("Remove this budget? Spend for {name} will no longer be limited.", { name: b.scope_name }))) {
                                  act(() => api.del(`/orgs/${orgId}/budgets/${b.id}`), tr("Budget removed."));
                                }
                              }}
                            >
                              {tr("Remove")}
                            </Button>
                          </>
                        ) : undefined
                      }
                    />
                  ))}
                </div>
              </Section>
            );
          })
        )}
        <p className="mt-4 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("When several budgets cover one person, the strictest wins: a budget that stops AI beats one that switches models. Room AI and other features that can't switch models keep using the normal model.")}
        </p>
      </ScreenBody>
    </div>
  );
}
