"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Key = {
  id: string;
  scope: "org" | "personal";
  provider: string;
  base_url: string;
  label: string;
  last4: string;
  status: string;
  last_error: string;
  last_checked_at: string | null;
  expires_at: string | null;
  created_at: string;
  demo?: boolean;
};
type Meta = { providers: string[]; allowed_hosts: string[]; can_manage_org_keys: boolean; private_only: boolean; demo_provider: boolean };
type Tone = "neutral" | "waiting" | "good" | "bad";

const STATUS: Record<string, [string, Tone]> = {
  pending: ["Checking", "waiting"],
  active: ["Active", "good"],
  rejected: ["Rejected", "bad"],
  indeterminate: ["Couldn't check", "waiting"],
  disabled: ["Turned off", "neutral"],
  expired: ["Expired", "bad"],
};
const ERRORS: Record<string, string> = {
  invalid_credential: "The provider refused this key. Check it and replace it.",
  provider_rejected: "The provider refused the check request.",
  rate_limited: "The provider is limiting requests. Test again in a few minutes.",
  provider_unavailable: "The provider did not answer. Test again later.",
  decrypt_failed: "This key can't be read any more. Replace it.",
  private_only: "Turned off because your organization only allows self-hosted models.",
};
const PROVIDERS: Record<string, string> = {
  openai: "OpenAI",
  openai_compatible: "OpenAI-compatible provider",
  demo: "Demo provider",
};

const EMPTY = { scope: "personal", provider: "openai", base_url: "", label: "", secret: "", expires: "" };

export function AiKeysScreen() {
  const { orgId } = useAccess();
  const tr = useTr();
  const meta = useOrgData<Meta>(orgId, "/credentials/meta");
  const keys = useOrgData<Key[]>(orgId, "/credentials", { list: true });
  const [form, setForm] = useState(EMPTY);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [rotate, setRotate] = useState<{ id: string; secret: string } | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const m = meta.data;
  const rows = rowsOf<Key>(keys.data);
  const personal = rows.filter((k) => k.scope === "personal");
  const org = rows.filter((k) => k.scope === "org");

  function failText(err: unknown) {
    const e = apiError(err);
    if (e.code === "private_only") return tr("Your organization only allows self-hosted models, so keys for external providers can't be used.");
    return errorText(err);
  }

  function resultText(key: Key) {
    if (key.status === "active") return tr("Key saved and working. You can pick its models in AI chat.");
    if (key.status === "rejected") return tr("Key saved, but the provider refused it. Nothing will use it until it passes a test.");
    return tr("Key saved, but it couldn't be checked yet. Test it again later.");
  }

  async function run(id: string, fn: () => Promise<unknown>, ok: string | ((v: unknown) => string)): Promise<boolean> {
    setBusy(id);
    setMessage(null);
    try {
      const v = await fn();
      setMessage({ kind: "ok", text: typeof ok === "string" ? ok : ok(v) });
      keys.reload();
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: failText(err) });
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function add(event: React.FormEvent) {
    event.preventDefault();
    const body: Record<string, string> = { scope: form.scope, provider: form.provider, label: form.label, secret: form.secret };
    if (form.provider === "openai_compatible") body.base_url = form.base_url;
    if (form.expires) body.expires_at = `${form.expires}T23:59:59Z`;
    const saved = await run("new", () => api.post<Key>(`/orgs/${orgId}/credentials`, body), (v) => resultText(v as Key));
    // The secret never stays in the page after a save attempt.
    setForm(saved ? EMPTY : { ...form, secret: "" });
    if (saved) setAdding(false);
  }

  function keyRow(k: Key) {
    const [label, tone] = STATUS[k.status] ?? [k.status, "neutral" as Tone];
    const providerName = PROVIDERS[k.provider] ? tr(PROVIDERS[k.provider]) : k.provider;
    return (
      <Row key={k.id} className="items-start">
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {k.label || providerName} <span className="font-normal text-[color:var(--fb-v2-text-muted)]">{tr("ending in {last4}", { last4: k.last4 })}</span>
          </p>
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
            {providerName}
            {k.provider === "openai_compatible" ? `, ${k.base_url.replace("https://", "")}` : ""}
            {k.last_checked_at ? `. ${tr("Last tested {when}.", { when: when(k.last_checked_at) })}` : ""}
            {k.expires_at ? ` ${tr("Expires {when}.", { when: when(k.expires_at) })}` : ""}
          </p>
          {k.demo ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Demo key. The demo model answers, nothing is sent to a provider.")}</p> : null}
          {k.last_error && k.status !== "active" ? (
            <p className="text-sm text-[color:var(--fb-v2-error)]">{ERRORS[k.last_error] ? tr(ERRORS[k.last_error]) : k.last_error}</p>
          ) : null}
          {rotate?.id === k.id ? (
            <form
              className="mt-2 flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const secret = rotate.secret;
                setRotate(null);
                run(k.id, () => api.patch<Key>(`/orgs/${orgId}/credentials/${k.id}`, { secret }), (v) => resultText(v as Key));
              }}
            >
              <label className="text-sm">
                <span className="mb-1 block font-medium">{tr("New key")}</span>
                <input
                  className="v2-input w-72"
                  type="password"
                  autoComplete="off"
                  required
                  minLength={8}
                  value={rotate.secret}
                  onChange={(e) => setRotate({ id: k.id, secret: e.target.value })}
                />
              </label>
              <Button type="submit">{tr("Replace and test")}</Button>
              <Button type="button" variant="ghost" onClick={() => setRotate(null)}>
                {tr("Cancel")}
              </Button>
            </form>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={tone}>{tr(label)}</Badge>
          {k.status !== "disabled" ? (
            <Button variant="outline" disabled={busy === k.id} onClick={() => run(k.id, () => api.patch<Key>(`/orgs/${orgId}/credentials/${k.id}`, { recheck: true }), (v) => resultText(v as Key))}>
              {busy === k.id ? tr("Testing…") : tr("Test")}
            </Button>
          ) : null}
          <Button
            variant="ghost"
            disabled={busy === k.id}
            onClick={() =>
              run(
                k.id,
                () => api.patch(`/orgs/${orgId}/credentials/${k.id}`, { status: k.status === "disabled" ? "enabled" : "disabled" }),
                k.status === "disabled" ? tr("Turned on and tested.") : tr("Turned off. Nothing will use this key."),
              )
            }
          >
            {k.status === "disabled" ? tr("Turn on") : tr("Turn off")}
          </Button>
          <Button variant="ghost" onClick={() => setRotate({ id: k.id, secret: "" })}>
            {tr("Replace")}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (window.confirm(tr("Remove this key? Chats that use it will stop working until you pick another model."))) {
                run(k.id, () => api.del(`/orgs/${orgId}/credentials/${k.id}`), tr("Key removed."));
              }
            }}
          >
            {tr("Remove")}
          </Button>
        </div>
      </Row>
    );
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("AI keys")}
        intro={tr("Use your own model provider keys. A key is stored encrypted and is never shown again after you save it. If a key stops working, FloBrain does not switch to another key.")}
        action={
          m && !m.private_only ? (
            <Button onClick={() => setAdding((v) => !v)}>{adding ? tr("Close") : tr("Add a key")}</Button>
          ) : undefined
        }
      />
      {m?.private_only ? (
        <Notice>{tr("Your organization only allows self-hosted models. Keys for external providers can't be added or turned on.")}</Notice>
      ) : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {adding && m ? (
        <form onSubmit={add} className="mb-8 rounded-xl bg-[color:var(--fb-v2-surface)] p-5" autoComplete="off">
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label={tr("Who can use it")}>
              <select className="v2-input" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
                <option value="personal">{tr("Only me")}</option>
                {m.can_manage_org_keys ? <option value="org">{tr("Owners and admins (org key)")}</option> : null}
              </select>
            </Field>
            <Field label={tr("Provider")}>
              <select className="v2-input" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                {m.providers.map((p) => (
                  <option key={p} value={p}>
                    {PROVIDERS[p] ? tr(PROVIDERS[p]) : p}
                  </option>
                ))}
              </select>
            </Field>
            {form.provider === "openai_compatible" ? (
              <Field label={tr("Provider address")} hint={tr("HTTPS only. Allowed: {hosts}", { hosts: m.allowed_hosts.join(", ") })}>
                <input
                  className="v2-input"
                  required
                  placeholder="https://openrouter.ai"
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                />
              </Field>
            ) : null}
            <Field label={tr("Name")} hint={tr("So you can tell your keys apart")}>
              <input className="v2-input" maxLength={80} value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
            </Field>
            <Field label={tr("Key")} hint={tr("Checked with the provider when you save it")}>
              <input
                className="v2-input"
                type="password"
                autoComplete="off"
                required
                minLength={8}
                maxLength={512}
                value={form.secret}
                onChange={(e) => setForm({ ...form, secret: e.target.value })}
              />
            </Field>
            <Field label={tr("Expires on (optional)")}>
              <input className="v2-input" type="date" value={form.expires} onChange={(e) => setForm({ ...form, expires: e.target.value })} />
            </Field>
          </div>
          <Button type="submit" variant={busy === "new" ? "waiting" : "default"} disabled={busy === "new"}>
            {busy === "new" ? tr("Checking the key…") : tr("Save and test")}
          </Button>
        </form>
      ) : null}
      <ScreenBody state={keys.state} error={keys.error} emptyLabel={tr("No keys yet. Without one, AI uses the platform models.")} onRetry={keys.reload}>
        <Section title={tr("Your keys")}>
          {personal.length ? <Rows>{personal.map(keyRow)}</Rows> : <Notice>{tr("You have no personal keys.")}</Notice>}
        </Section>
        {m?.can_manage_org_keys ? (
          <Section title={tr("Organization keys")}>
            {org.length ? <Rows>{org.map(keyRow)}</Rows> : <Notice>{tr("No organization keys. Owners and admins can add one.")}</Notice>}
          </Section>
        ) : null}
      </ScreenBody>
    </div>
  );
}
