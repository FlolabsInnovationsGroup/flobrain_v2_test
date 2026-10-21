"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { KIND_LABEL, connectionTone, embedSnippet, parseOrigins, randomToken, type ChannelKind, type Connection } from "./logic";

const STATUS: Record<Connection["status"], string> = { not_set_up: "Not set up", active: "Active", error: "Error" };
const ERRORS: Record<string, string> = {
  invalid_credentials: "The provider refused the credentials.",
  missing_settings: "Some settings are missing.",
  provider_unavailable: "The provider did not answer. Try again later.",
  provider_rejected: "The provider rejected the request. Check the IDs.",
  rate_limited: "The provider asked us to slow down. Try again later.",
  decrypt_failed: "The saved secrets can't be read. Enter them again.",
  disconnected: "Disconnected.",
};

function Copyable({ label, value }: { label: string; value: string }) {
  const tr = useTr();
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2">
      <p className="text-xs font-medium">{label}</p>
      <div className="mt-1 flex flex-wrap items-start gap-2">
        <code className="block min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-[color:var(--fb-v2-raised)] p-2 text-xs" dir="ltr">
          {value}
        </code>
        <Button
          variant="outline"
          onClick={() =>
            void navigator.clipboard?.writeText(value).then(
              () => setCopied(true),
              () => setCopied(false),
            )
          }
        >
          {copied ? tr("Copied") : tr("Copy")}
        </Button>
      </div>
    </div>
  );
}

function ConnectionCard({ orgId, c, onChange }: { orgId: string; c: Connection; onChange: () => void }) {
  const tr = useTr();
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const appOrigin = typeof window === "undefined" ? "" : window.location.origin;

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMessage(null);
    try {
      const res = await api.post<Connection>(`/orgs/${orgId}/channels/connections/${c.id}/test`);
      setMessage(
        res.status === "active"
          ? { kind: "ok", text: res.simulated ? tr("Connected (simulated, no message left FloBrain).") : tr("Connected.") }
          : { kind: "error", text: tr(ERRORS[res.last_error] ?? "The test failed.") },
      );
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  const contact = c.config.display_phone || (c.config.bot_username ? `@${c.config.bot_username}` : "");
  return (
    <li className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{c.label || tr(KIND_LABEL[c.kind])}</p>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr(KIND_LABEL[c.kind])}
            {contact ? ` · ${contact}` : ""}
            {c.last_checked_at ? ` · ${tr("Checked {time}", { time: when(c.last_checked_at) })}` : ""}
          </p>
        </div>
        <span className="flex flex-wrap gap-1">
          {c.demo ? <Badge>{tr("Demo")}</Badge> : null}
          <Badge tone={connectionTone(c.status)}>{tr(STATUS[c.status])}</Badge>
        </span>
      </div>
      <p className="text-sm">
        {[c.serve_team ? tr("Your team talks to buddies here") : "", c.serve_customers ? tr("Customers talk to the customer buddy here") : ""].filter(Boolean).join(". ")}
        {c.serve_team ? ` ${tr("{n} people linked.", { n: c.linked_people })}` : ""}
      </p>
      {c.status === "error" && c.last_error ? <p className="text-sm text-[color:var(--fb-v2-error)]">{tr(ERRORS[c.last_error] ?? "The last test failed.")}</p> : null}
      {Object.keys(c.secret_hints).length ? (
        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
          {tr("Saved secrets:")}{" "}
          <span dir="ltr">{Object.entries(c.secret_hints).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ")}</span>
        </p>
      ) : null}
      {c.webhook_url && !c.demo ? <Copyable label={tr("Webhook address for the provider")} value={c.webhook_url} /> : null}
      {c.kind === "website" && c.site_key ? (
        <>
          <Copyable label={tr("Paste this before </body> on your website")} value={embedSnippet(appOrigin, c.site_key)} />
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("Allowed websites: {list}", { list: (c.config.allowed_origins ?? []).join(", ") || "-" })}
          </p>
          <a className="text-sm underline" href={`/p/chat/${c.site_key}`} target="_blank" rel="noreferrer">
            {tr("Open the chat page")}
          </a>
        </>
      ) : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <div className="mt-auto flex flex-wrap gap-2 pt-2">
        <Button variant="outline" disabled={busy} onClick={test}>
          {tr("Test connection")}
        </Button>
        {c.kind !== "website" ? (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => act(() => api.patch(`/orgs/${orgId}/channels/connections/${c.id}`, { serve_customers: !c.serve_customers }), tr("Saved."))}
          >
            {c.serve_customers ? tr("Stop serving customers") : tr("Serve customers here too")}
          </Button>
        ) : null}
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm(tr("Disconnect? The secrets are deleted and everyone linked here is unlinked."))) {
              void act(() => api.del(`/orgs/${orgId}/channels/connections/${c.id}`), tr("Disconnected."));
            }
          }}
        >
          {tr("Disconnect")}
        </Button>
      </div>
    </li>
  );
}

type FormState = Record<string, string>;

function ConnectForm({ orgId, demo, onDone }: { orgId: string; demo: boolean; onDone: () => void }) {
  const tr = useTr();
  const [kind, setKind] = useState<ChannelKind>("whatsapp");
  const [form, setForm] = useState<FormState>({});
  const [serveCustomers, setServeCustomers] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const input = (key: string, label: string, hint?: string, secret = false) => (
    <Field label={label} hint={hint}>
      <input className="v2-input w-full" dir="ltr" type={secret ? "password" : "text"} autoComplete="off" value={form[key] ?? ""} onChange={set(key)} />
    </Field>
  );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    const body =
      kind === "whatsapp"
        ? {
            kind,
            label: form.label,
            serve_customers: serveCustomers,
            config: { phone_number_id: form.phone_number_id, waba_id: form.waba_id, display_phone: form.display_phone },
            secrets: { access_token: form.access_token, app_secret: form.app_secret, verify_token: form.verify_token },
          }
        : kind === "telegram"
          ? { kind, label: form.label, serve_customers: serveCustomers, secrets: { bot_token: form.bot_token, secret_token: form.secret_token } }
          : { kind, label: form.label, config: { allowed_origins: parseOrigins(form.origins ?? "") } };
    try {
      await api.post(`/orgs/${orgId}/channels/connections`, body);
      setForm({});
      setMessage({ kind: "ok", text: demo ? tr("Connected in demo mode. Nothing reaches a real provider.") : tr("Saved. Test the connection next.") });
      onDone();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <form className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" onSubmit={submit}>
      <fieldset className="mb-4 flex flex-wrap gap-2">
        <legend className="mb-2 text-sm font-medium">{tr("What do you want to connect?")}</legend>
        {(["whatsapp", "telegram", "website"] as ChannelKind[]).map((k) => (
          <label key={k} className={`cursor-pointer rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[color:var(--fb-v2-accent)] ${kind === k ? "bg-[color:var(--fb-v2-accent)] text-white" : ""}`}>
            <input className="sr-only" type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} />
            {tr(KIND_LABEL[k])}
          </label>
        ))}
      </fieldset>
      {demo ? <Notice>{tr("Demo mode: the connection is simulated and the secrets you type are not stored.")}</Notice> : null}
      {input("label", tr("Name"), tr("For example: Sales WhatsApp"))}
      {kind === "whatsapp" ? (
        <>
          {input("phone_number_id", tr("Phone number ID"), tr("From Meta: WhatsApp, API setup."))}
          {input("waba_id", tr("WhatsApp Business account ID"))}
          {input("display_phone", tr("Phone number shown to people"), tr("For example: +20 100 000 0001"))}
          {input("access_token", tr("Access token"), tr("A permanent system user token with whatsapp_business_messaging."), true)}
          {input("app_secret", tr("App secret"), tr("From Meta: App settings, Basic. Used to check every webhook."), true)}
          <Field label={tr("Verify token")} hint={tr("Any random text. Paste the same text in Meta when you add the webhook.")}>
            <span className="flex gap-2">
              <input className="v2-input w-full" dir="ltr" autoComplete="off" value={form.verify_token ?? ""} onChange={set("verify_token")} />
              <Button type="button" variant="outline" onClick={() => setForm((f) => ({ ...f, verify_token: randomToken(24) }))}>
                {tr("Generate")}
              </Button>
            </span>
          </Field>
        </>
      ) : null}
      {kind === "telegram" ? (
        <>
          {input("bot_token", tr("Bot token"), tr("From @BotFather. It looks like 123456:ABC..."), true)}
          <Field label={tr("Secret token")} hint={tr("Any random text, 16 characters or more. Use it as secret_token when you call setWebhook.")}>
            <span className="flex gap-2">
              <input className="v2-input w-full" dir="ltr" autoComplete="off" value={form.secret_token ?? ""} onChange={set("secret_token")} />
              <Button type="button" variant="outline" onClick={() => setForm((f) => ({ ...f, secret_token: randomToken(32) }))}>
                {tr("Generate")}
              </Button>
            </span>
          </Field>
        </>
      ) : null}
      {kind === "website" ? (
        <Field label={tr("Websites that may show the chat")} hint={tr("One per line, like https://www.example.com")}>
          <textarea className="v2-input min-h-20 w-full" dir="ltr" value={form.origins ?? ""} onChange={set("origins")} />
        </Field>
      ) : (
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={serveCustomers} onChange={(e) => setServeCustomers(e.target.checked)} />
          {tr("Customers can write here too (the customer buddy answers them)")}
        </label>
      )}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Button type="submit">{tr("Connect")}</Button>
    </form>
  );
}

export function ConnectionsPanel({ orgId, demo }: { orgId: string; demo: boolean }) {
  const tr = useTr();
  const { data, reload } = useOrgData<Connection[]>(orgId, "/channels/connections");
  const rows = rowsOf<Connection>(data);
  const [adding, setAdding] = useState(false);
  return (
    <Section
      title={tr("Connections")}
      aside={
        <Button variant="outline" aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
          {adding ? tr("Close") : tr("Connect a channel")}
        </Button>
      }
    >
      {adding ? (
        <div className="mb-4">
          <ConnectForm orgId={orgId} demo={demo} onDone={reload} />
        </div>
      ) : null}
      {rows.length === 0 ? <Notice>{tr("Nothing connected yet.")}</Notice> : null}
      <ul className="grid gap-3 md:grid-cols-2">
        {rows.map((c) => (
          <ConnectionCard key={c.id} orgId={orgId} c={c} onChange={reload} />
        ))}
      </ul>
    </Section>
  );
}
