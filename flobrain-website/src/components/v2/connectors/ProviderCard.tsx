"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { cardActions, odooFormProblem, riskLabel, scopeLabel, statusBadge, type WriteAction, type WriteConnection, type WriteProvider } from "./connectors";

const focusRing = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fb-v2-accent)]";

export type OdooForm = { url: string; database: string; login: string; api_key: string };

type Props = {
  provider: WriteProvider;
  canManage: boolean;
  canAct: boolean;
  demo: boolean;
  busy: boolean;
  onConnect: (scope: "org" | "personal") => void;
  onConnectOdoo: (form: OdooForm) => Promise<boolean>;
  onDisconnect: (connection: WriteConnection) => void;
  onToggle: (action: WriteAction, enabled: boolean) => void;
};

export function ProviderCard({ provider: p, canManage, canAct, demo, busy, onConnect, onConnectOdoo, onDisconnect, onToggle }: Props) {
  const tr = useTr();
  const can = cardActions(p, canManage, canAct, demo);
  const badge = statusBadge(p.status);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<OdooForm>({ url: "", database: "", login: "", api_key: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const odooForm = can.apiKeyForm && !demo;

  function startOrg() {
    if (odooForm) setFormOpen(true);
    else onConnect("org");
  }

  async function submitOdoo(e: React.FormEvent) {
    e.preventDefault();
    const issue = odooFormProblem(form);
    setProblem(issue);
    if (issue) return;
    if (await onConnectOdoo(form)) {
      setFormOpen(false);
      setForm({ url: "", database: "", login: "", api_key: "" });
    }
  }

  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold">{p.name}</h3>
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr(p.description)}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge tone={badge.tone}>{tr(badge.label)}</Badge>
          {p.simulated ? <Badge>{tr("Simulated")}</Badge> : null}
        </div>
      </div>

      {p.connection ? <ConnectionLine connection={p.connection} label={tr("Organization account")} /> : null}
      {p.personal ? <ConnectionLine connection={p.personal} label={tr("Your account")} /> : null}
      {p.status === "not_set_up" ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
          {p.env?.length
            ? tr("Not set up on this server yet. An operator adds {names} to the server settings.", { names: p.env.join(", ") })
            : tr("Not set up on this server yet. Ask your admin.")}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {can.connectOrg ? (
          <Button variant="outline" disabled={busy} onClick={startOrg}>
            {p.per_user ? tr("Connect for everyone") : tr("Connect")}
          </Button>
        ) : null}
        {can.reconnectOrg ? (
          <Button variant="outline" disabled={busy} onClick={startOrg}>
            {tr("Connect again")}
          </Button>
        ) : null}
        {can.connectPersonal ? (
          <Button variant="outline" disabled={busy} onClick={() => onConnect("personal")}>
            {tr("Connect my account")}
          </Button>
        ) : null}
        {can.disconnectOrg && p.connection ? (
          <Button variant="danger" disabled={busy} onClick={() => onDisconnect(p.connection as WriteConnection)}>
            {tr("Disconnect")}
          </Button>
        ) : null}
        {can.disconnectPersonal && p.personal ? (
          <Button variant="danger" disabled={busy} onClick={() => onDisconnect(p.personal as WriteConnection)}>
            {tr("Disconnect my account")}
          </Button>
        ) : null}
      </div>

      {formOpen && odooForm ? (
        <form className="rounded-lg bg-[color:var(--fb-v2-raised)] p-3" onSubmit={submitOdoo}>
          <Field label={tr("Odoo address")} hint={tr("Your odoo.com address, or a host your operator allowed.")}>
            <input className="v2-input" dir="ltr" inputMode="url" placeholder="https://yourcompany.odoo.com" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </Field>
          <Field label={tr("Database")}>
            <input className="v2-input" dir="ltr" value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} />
          </Field>
          <Field label={tr("Login")}>
            <input className="v2-input" dir="ltr" autoComplete="off" value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} />
          </Field>
          <Field label={tr("API key")} hint={tr("Stored encrypted and never shown again. Only the last 4 characters are shown.")}>
            <input className="v2-input" dir="ltr" type="password" autoComplete="new-password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </Field>
          {problem ? <Notice kind="error">{tr(problem)}</Notice> : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy}>
              {tr("Check and connect")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setFormOpen(false)}>
              {tr("Cancel")}
            </Button>
          </div>
        </form>
      ) : null}

      <details className="group">
        <summary className={`cursor-pointer rounded text-sm font-medium ${focusRing}`}>{tr("What buddies can ask to do ({n})", { n: p.actions.length })}</summary>
        <ul className="mt-2 divide-y divide-[color:var(--fb-v2-border)]">
          {p.actions.map((a) => (
            <li key={a.tool} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div className="min-w-0">
                <p className="text-sm">{tr(a.label)}</p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr(riskLabel(a.risk))}</p>
              </div>
              {canManage ? (
                <ActionSwitch label={tr(a.label)} on={a.enabled} disabled={busy} onChange={(next) => onToggle(a, next)} />
              ) : a.enabled ? null : (
                <Badge>{tr("Off")}</Badge>
              )}
            </li>
          ))}
        </ul>
      </details>
      {p.scopes.length ? (
        <details>
          <summary className={`cursor-pointer rounded text-sm font-medium ${focusRing}`}>{tr("Permissions it asks for")}</summary>
          <ul className="mt-2 flex flex-wrap gap-1" dir="ltr">
            {p.scopes.map((s) => (
              <li key={s} className="rounded-full bg-[color:var(--fb-v2-raised)] px-2 py-0.5 font-mono text-xs" title={s}>
                {scopeLabel(s)}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}

function ConnectionLine({ connection: c, label }: { connection: WriteConnection; label: string }) {
  const tr = useTr();
  return (
    <div className="text-sm">
      <p>
        <span className="text-[color:var(--fb-v2-text-muted)]">{label}: </span>
        <span className="break-all font-medium">{c.account_label}</span>
        {c.secret_hint ? <span className="ms-1 font-mono text-xs text-[color:var(--fb-v2-text-muted)]" dir="ltr">({tr("key")} {c.secret_hint})</span> : null}
      </p>
      <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
        {c.simulated ? tr("Simulated demo connection. Approved actions return example links and never contact the real service.") : tr("Connected {when}.", { when: when(c.connected_at) })}
        {c.last_used_at ? ` ${tr("Last used {when}.", { when: when(c.last_used_at) })}` : ""}
        {c.status !== "connected" ? ` ${tr("Connect it again to keep using it.")}` : ""}
      </p>
    </div>
  );
}

function ActionSwitch({ label, on, disabled, onChange }: { label: string; on: boolean; disabled: boolean; onChange: (next: boolean) => void }) {
  const tr = useTr();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`inline-flex min-h-9 items-center gap-2 rounded-full px-2 text-xs ${focusRing} disabled:opacity-50`}
    >
      <span
        aria-hidden
        className={`relative inline-block h-5 w-9 rounded-full transition-colors ${on ? "bg-[color:var(--fb-v2-success)]" : "bg-[color:var(--fb-v2-track)]"}`}
      >
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${on ? "start-[1.125rem]" : "start-0.5"}`} />
      </span>
      {on ? tr("On") : tr("Off")}
    </button>
  );
}
