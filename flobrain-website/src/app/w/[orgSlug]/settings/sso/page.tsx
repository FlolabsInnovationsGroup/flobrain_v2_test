"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Protocol = "oidc" | "saml";
type Sso = {
  protocol: Protocol;
  issuer: string;
  client_id: string;
  idp_entity_id: string;
  idp_sso_url: string;
  idp_cert_fingerprint: string;
  idp_cert_expires_at: string | null;
  email_attribute: string;
  saml_complete: boolean;
  sp_entity_id: string;
  acs_url: string;
  metadata_url: string;
  verified_domains: string[];
  pending_domains: { domain: string; txt_name: string; txt_value: string }[];
  enforced: boolean;
  enabled: boolean;
  redirect_uri: string;
};
const SAML_FIELDS = ["idp_entity_id", "idp_sso_url", "idp_certificate", "email_attribute"] as const;
type SamlForm = Record<(typeof SAML_FIELDS)[number], string>;

/** Only the SAML fields the owner filled in, so details can be saved one at a time. */
function samlBody(form: SamlForm) {
  const body: Record<string, string> = { protocol: "saml" };
  for (const key of SAML_FIELDS) if (form[key].trim()) body[key] = form[key].trim();
  return body;
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const tr = useTr();
  return (
    <Row className="items-start">
      <div className="min-w-0 text-sm">
        <p className="font-medium">{label}</p>
        <code className="break-all">{value}</code>
      </div>
      <Button variant="outline" onClick={() => navigator.clipboard?.writeText(value)}>
        {tr("Copy")}
      </Button>
    </Row>
  );
}

type Scim = { tokens: { id: string; last4: string; revoked: boolean }[]; groups: { id: string; display_name: string; team: string | null }[] };

export default function SsoPage() {
  const tr = useTr();
  const { orgId } = useAccess();
  const sso = useOrgData<Sso | null>(orgId, "/sso");
  const scim = useOrgData<Scim>(orgId, "/scim/tokens");
  const { data: teams } = useOrgData<{ id: string; name: string }[]>(orgId, "/teams");
  const [form, setForm] = useState({ issuer: "", client_id: "", client_secret: "" });
  const [samlForm, setSamlForm] = useState<SamlForm>({ idp_entity_id: "", idp_sso_url: "", idp_certificate: "", email_attribute: "" });
  const [picked, setPicked] = useState<Protocol | null>(null);
  const [domain, setDomain] = useState("");
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const c = sso.data;
  const protocol: Protocol = picked ?? c?.protocol ?? "oidc";
  const saml = c?.protocol === "saml" ? c : null;

  async function act<T>(fn: () => Promise<T>, ok: string, after?: (v: T) => void) {
    setMessage(null);
    try {
      const value = await fn();
      setMessage({ kind: "ok", text: ok });
      after?.(value);
      sso.reload();
      scim.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("SSO and provisioning")}
        intro={tr("Let people sign in with your identity provider (Google Workspace, Entra ID, Okta), and add or pause them automatically with SCIM.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={sso.state} error={sso.error} onRetry={sso.reload}>
        <Section title={tr("1. Connect your identity provider")}>
          <fieldset className="mb-3 flex flex-wrap gap-4 text-sm">
            <legend className="mb-1 font-medium">{tr("Protocol")}</legend>
            {(["oidc", "saml"] as const).map((p) => (
              <label key={p} className="flex items-center gap-2">
                <input type="radio" name="sso-protocol" checked={protocol === p} onChange={() => setPicked(p)} />
                {p === "oidc" ? tr("OpenID Connect (OIDC)") : tr("SAML 2.0")}
              </label>
            ))}
          </fieldset>
          {c && protocol !== c.protocol ? <Notice>{tr("Changing the protocol switches SSO off until you turn it on again below.")}</Notice> : null}
          {protocol === "oidc" ? (
            <form
              className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
              onSubmit={(e) => {
                e.preventDefault();
                act(() => api.put(`/orgs/${orgId}/sso`, { ...form, protocol: "oidc" }), tr("Saved. If you changed the provider, switch SSO on again below."), () => setPicked(null));
              }}
            >
              {c?.protocol === "oidc" ? (
                <p className="mb-3 text-sm">
                  {tr("Connected to")} <strong>{c.issuer}</strong> {tr("with client ID")} <code>{c.client_id}</code>.
                </p>
              ) : null}
              <Field label={tr("Issuer URL")} hint={tr("For Google: {url}", { url: "https://accounts.google.com" })}>
                <input className="v2-input" type="url" required value={form.issuer} onChange={(e) => setForm({ ...form, issuer: e.target.value })} />
              </Field>
              <Field label={tr("Client ID")}>
                <input className="v2-input" required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} />
              </Field>
              <Field label={tr("Client secret")} hint={tr("Stored encrypted and never shown again.")}>
                <input className="v2-input" type="password" required value={form.client_secret} onChange={(e) => setForm({ ...form, client_secret: e.target.value })} />
              </Field>
              <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr("Redirect URI to register with the provider:")} <code>{c?.redirect_uri ?? "/api/v2/sso/callback"}</code>
              </p>
              <Button type="submit">{c?.protocol === "oidc" ? tr("Update connection") : tr("Connect")}</Button>
            </form>
          ) : (
            <form
              className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
              onSubmit={(e) => {
                e.preventDefault();
                act(() => api.put(`/orgs/${orgId}/sso`, samlBody(samlForm)), tr("Saved. If you changed the provider, switch SSO on again below."), () => {
                  setPicked(null);
                  setSamlForm({ ...samlForm, idp_certificate: "" });
                });
              }}
            >
              {saml ? (
                <div className="mb-4">
                  <p className="mb-2 text-sm">{tr("Give these to your identity provider:")}</p>
                  <Rows>
                    <CopyRow label={tr("ACS URL (Reply URL)")} value={saml.acs_url} />
                    <CopyRow label={tr("SP entity ID (Audience)")} value={saml.sp_entity_id} />
                    <CopyRow label={tr("Metadata URL")} value={saml.metadata_url} />
                  </Rows>
                  <p className="mt-2 text-sm">
                    <a className="underline" href={saml.metadata_url} target="_blank" rel="noreferrer">
                      {tr("Open the metadata XML")}
                    </a>
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                    {saml.saml_complete ? (
                      <Badge tone="good">{tr("Ready")}</Badge>
                    ) : (
                      <Badge tone="waiting">{tr("Add the IdP entity ID, sign-in URL and certificate")}</Badge>
                    )}
                    {saml.idp_entity_id ? (
                      <span>
                        {tr("IdP entity ID")}: <code className="break-all">{saml.idp_entity_id}</code>
                      </span>
                    ) : null}
                  </div>
                  {saml.idp_cert_fingerprint ? (
                    <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("Certificate {fingerprint}, valid until {date}", {
                        fingerprint: saml.idp_cert_fingerprint,
                        date: saml.idp_cert_expires_at ? new Date(saml.idp_cert_expires_at).toLocaleDateString() : "?",
                      })}
                    </p>
                  ) : null}
                </div>
              ) : (
                <Notice>{tr("Save once to get the ACS URL and metadata for your identity provider.")}</Notice>
              )}
              <Field label={tr("IdP entity ID")} hint={tr("Also called Issuer or Identifier in your provider's SAML app.")}>
                <input
                  className="v2-input"
                  placeholder={saml?.idp_entity_id || undefined}
                  value={samlForm.idp_entity_id}
                  onChange={(e) => setSamlForm({ ...samlForm, idp_entity_id: e.target.value })}
                />
              </Field>
              <Field label={tr("IdP sign-in URL")} hint={tr("The SSO URL for the HTTP-Redirect binding. It must start with https://.")}>
                <input
                  className="v2-input"
                  type="url"
                  placeholder={saml?.idp_sso_url || "https://"}
                  value={samlForm.idp_sso_url}
                  onChange={(e) => setSamlForm({ ...samlForm, idp_sso_url: e.target.value })}
                />
              </Field>
              <Field label={tr("IdP signing certificate")} hint={tr("Paste the certificate (PEM or base64). Leave it empty to keep the current one.")}>
                <textarea
                  className="v2-input min-h-28 font-mono text-xs"
                  placeholder="-----BEGIN CERTIFICATE-----"
                  value={samlForm.idp_certificate}
                  onChange={(e) => setSamlForm({ ...samlForm, idp_certificate: e.target.value })}
                />
              </Field>
              <Field label={tr("Email attribute")} hint={tr("Leave it empty to use the NameID in email format, or an attribute named email.")}>
                <input
                  className="v2-input"
                  placeholder={saml?.email_attribute || "email"}
                  value={samlForm.email_attribute}
                  onChange={(e) => setSamlForm({ ...samlForm, email_attribute: e.target.value })}
                />
              </Field>
              <Button type="submit">{saml ? tr("Update connection") : tr("Save")}</Button>
            </form>
          )}
        </Section>

        {c ? (
          <>
            <Section title={tr("2. Prove you own your email domain")}>
              <form
                className="mb-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  act(() => api.post(`/orgs/${orgId}/sso/domains`, { domain }), tr("Add the DNS record below, then check it."), () => setDomain(""));
                }}
              >
                <input className="v2-input" placeholder="yourcompany.com" value={domain} onChange={(e) => setDomain(e.target.value)} aria-label={tr("Domain")} />
                <Button type="submit" variant="outline">
                  {tr("Add domain")}
                </Button>
              </form>
              <Rows>
                {c.verified_domains.map((d) => (
                  <Row key={d}>
                    <span>{d}</span>
                    <Badge tone="good">{tr("Verified")}</Badge>
                  </Row>
                ))}
                {c.pending_domains.map((p) => (
                  <Row key={p.domain} className="items-start">
                    <div className="min-w-0 text-sm">
                      <p className="font-medium">{p.domain}</p>
                      <p className="text-[color:var(--fb-v2-text-muted)]">
                        {tr("Add a TXT record named")} <code>{p.txt_name}</code> {tr("with the value")} <code className="break-all">{p.txt_value}</code>
                      </p>
                    </div>
                    <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/sso/domains/${p.domain}/verify`), tr("Domain verified."))}>
                      {tr("Check now")}
                    </Button>
                  </Row>
                ))}
              </Rows>
            </Section>

            <Section title={tr("3. Switch it on")}>
              <div className="space-y-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm">
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={c.enabled}
                    disabled={!c.verified_domains.length || (c.protocol === "saml" && !c.saml_complete)}
                    onChange={(e) => act(() => api.put(`/orgs/${orgId}/sso`, { enabled: e.target.checked }), e.target.checked ? tr("SSO is on.") : tr("SSO is off."))}
                  />
                  {tr("People with a verified email can sign in with SSO")}
                </label>
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={c.enforced}
                    disabled={!c.enabled}
                    onChange={(e) =>
                      act(
                        () => api.put(`/orgs/${orgId}/sso`, { enforced: e.target.checked }),
                        e.target.checked ? tr("SSO is required. Existing password sessions were signed out. You keep your password as a backup.") : tr("Passwords work again."),
                      )
                    }
                  />
                  {tr("Require SSO (passwords stop working for everyone except you, the owner)")}
                </label>
              </div>
            </Section>
          </>
        ) : null}

        <Section title={tr("Provisioning (SCIM)")}>
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("Your identity provider adds people in your verified domains as members and pauses them when they leave. It never makes anyone an admin or lead.")}{" "}
            {tr("Base URL:")} <code>/scim/v2</code>
          </p>
          {secret ? (
            <div className="my-3 rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]">
              <p className="text-sm font-medium">{tr("SCIM token. Copy it now: it won't be shown again.")}</p>
              <code className="mt-1 block break-all text-sm">{secret}</code>
            </div>
          ) : null}
          <Button variant="outline" onClick={() => act(() => api.post<{ token: string }>(`/orgs/${orgId}/scim/tokens`), tr("Token created."), (v) => setSecret(v.token))}>
            {tr("Create SCIM token")}
          </Button>
          <ScreenBody state={scim.state} error={scim.error} onRetry={scim.reload}>
            <Rows>
              {(scim.data?.tokens ?? []).map((t) => (
                <Row key={t.id}>
                  <span>{tr("Token …{last4}", { last4: t.last4 })}</span>
                  {t.revoked ? (
                    <Badge>{tr("Revoked")}</Badge>
                  ) : (
                    <Button variant="danger" onClick={() => act(() => api.post(`/orgs/${orgId}/scim/tokens`, { revoke: t.id }), tr("Revoked."))}>
                      {tr("Revoke")}
                    </Button>
                  )}
                </Row>
              ))}
              {(scim.data?.groups ?? []).map((g) => (
                <Row key={g.id}>
                  <span>{tr("Group “{name}”", { name: g.display_name })}</span>
                  <select
                    className="v2-input w-56"
                    aria-label={tr("Team for {name}", { name: g.display_name })}
                    value={g.team ?? ""}
                    onChange={(e) => act(() => api.post(`/orgs/${orgId}/scim/tokens`, { map_group: g.id, team: e.target.value || null }), tr("Mapping saved."))}
                  >
                    <option value="">{tr("No team")}</option>
                    {rowsOf<{ id: string; name: string }>(teams).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </Section>
      </ScreenBody>
    </div>
  );
}
