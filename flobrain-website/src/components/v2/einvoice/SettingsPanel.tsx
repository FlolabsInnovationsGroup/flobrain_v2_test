"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import type { Meta, Profile } from "./types";

const input =
  "w-full rounded-lg bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]";

type Msg = { kind: "ok" | "error"; text: string } | null;
const STEPS = ["none", "key_ready", "compliance_csid", "checks_passed", "production"] as const;

function TextInput({ label, value, onChange, hint, ltr, max = 200, type = "text", placeholder }: { label: string; value: string; onChange: (v: string) => void; hint?: string; ltr?: boolean; max?: number; type?: string; placeholder?: string }) {
  return (
    <Field label={label} hint={hint}>
      <input className={input} type={type} value={value} onChange={(e) => onChange(e.target.value)} maxLength={max} dir={ltr ? "ltr" : undefined} placeholder={placeholder} autoComplete="off" />
    </Field>
  );
}

function useProfileForm(profile: Profile | null, keys: string[]) {
  const [form, setForm] = useState<Record<string, string>>(() => Object.fromEntries(keys.map((k) => [k, String((profile as Record<string, unknown> | null)?.[k] ?? "")])));
  return { form, set: (k: string) => (v: string) => setForm((f) => ({ ...f, [k]: v })) };
}

const SA_KEYS = ["seller_name", "seller_name_ar", "tax_number", "registration_scheme", "registration_id", "street", "building_number", "district", "city", "postal_code", "environment", "egs_serial", "egs_common_name", "branch_name", "functionality_map", "egs_location", "industry"];
const EG_KEYS = ["seller_name", "seller_name_ar", "tax_number", "registration_id", "activity_code", "region", "city", "street", "building_number", "postal_code", "environment", "client_id", "signer_mode", "signer_url"];

export function SaudiSettings({ orgId, meta, onChange }: { orgId: string; meta: Meta; onChange: () => void }) {
  const tr = useTr();
  const profile = meta.profiles.SA;
  const { form, set } = useProfileForm(profile, SA_KEYS);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const step = profile?.onboarding ?? "none";
  const at = STEPS.indexOf(step);
  const locked = at > 0 && !profile?.simulated;

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key);
    setMsg(null);
    try {
      await fn();
      setMsg({ kind: "ok", text: ok });
      onChange();
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  const save = () => run("save", () => api.put(`/orgs/${orgId}/einvoice/settings/SA`, { ...form, environment: form.environment || "sandbox", functionality_map: form.functionality_map || "1100", registration_scheme: form.registration_scheme || "CRN" }), tr("Saved."));
  const stepItems = [
    { key: "key", title: tr("Create the unit's key and CSR"), body: tr("FloBrain makes a private key for this invoicing unit and keeps it encrypted. It never leaves the server.") },
    { key: "compliance", title: tr("Get the compliance certificate"), body: tr("In the Fatoora portal, generate an OTP (valid for one hour) and paste it here.") },
    { key: "checks", title: tr("Run the compliance checks"), body: tr("FloBrain sends sample invoices and notes for each type you chose, signed with the compliance certificate.") },
    { key: "production", title: tr("Get the production certificate"), body: tr("After the checks pass, ZATCA issues the certificate used for real invoices.") },
  ];

  return (
    <div className="flex flex-col gap-2">
      {profile?.simulated ? <Notice>{tr("Demo: onboarding is simulated with a self-signed certificate. Nothing is sent to ZATCA.")}</Notice> : null}
      <Section title={tr("Seller")}>
        <div className="grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          <TextInput label={tr("Legal name")} value={form.seller_name} onChange={set("seller_name")} />
          <TextInput label={tr("Legal name in Arabic")} value={form.seller_name_ar} onChange={set("seller_name_ar")} />
          <TextInput label={tr("VAT number")} value={form.tax_number} onChange={set("tax_number")} hint={tr("15 digits, starts and ends with 3.")} ltr max={15} />
          <Field label={tr("Registration")}>
            <div className="flex gap-2">
              <select className={`${input} w-28`} value={form.registration_scheme || "CRN"} onChange={(e) => set("registration_scheme")(e.target.value)} aria-label={tr("ID type")}>
                {["CRN", "MOM", "MLS", "700", "SAG", "OTH"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <input className={input} value={form.registration_id} onChange={(e) => set("registration_id")(e.target.value)} dir="ltr" maxLength={40} aria-label={tr("ID number")} />
            </div>
          </Field>
          <TextInput label={tr("Street")} value={form.street} onChange={set("street")} />
          <TextInput label={tr("Building number")} value={form.building_number} onChange={set("building_number")} hint={tr("4 digits")} ltr max={4} />
          <TextInput label={tr("District")} value={form.district} onChange={set("district")} />
          <TextInput label={tr("City")} value={form.city} onChange={set("city")} />
          <TextInput label={tr("Postal code")} value={form.postal_code} onChange={set("postal_code")} hint={tr("5 digits")} ltr max={5} />
        </div>
      </Section>
      <Section title={tr("Invoicing unit (EGS)")}>
        <div className="grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={tr("Environment")} hint={locked ? tr("Reset onboarding to change it.") : undefined}>
            <select className={input} value={form.environment || "sandbox"} onChange={(e) => set("environment")(e.target.value)} disabled={locked}>
              <option value="sandbox">{tr("Developer portal (sandbox)")}</option>
              <option value="simulation">{tr("Simulation")}</option>
              <option value="production">{tr("Production")}</option>
            </select>
          </Field>
          <TextInput label={tr("Unit name")} value={form.egs_common_name} onChange={set("egs_common_name")} max={64} ltr />
          <TextInput label={tr("Serial number")} value={form.egs_serial} onChange={set("egs_serial")} hint={tr("Like 1-Solution|2-Version|3-Serial")} ltr />
          <TextInput label={tr("Branch name")} value={form.branch_name} onChange={set("branch_name")} />
          <Field label={tr("Invoice types")}>
            <select className={input} value={form.functionality_map || "1100"} onChange={(e) => set("functionality_map")(e.target.value)}>
              <option value="1100">{tr("Standard and simplified")}</option>
              <option value="1000">{tr("Standard only")}</option>
              <option value="0100">{tr("Simplified only")}</option>
            </select>
          </Field>
          <TextInput label={tr("Branch address (short national address)")} value={form.egs_location} onChange={set("egs_location")} ltr />
          <TextInput label={tr("Industry")} value={form.industry} onChange={set("industry")} />
        </div>
        <Button onClick={save} disabled={!!busy}>{busy === "save" ? tr("Saving…") : tr("Save")}</Button>
      </Section>

      <Section title={tr("ZATCA onboarding")} aside={<Badge tone={step === "production" ? "good" : "neutral"}>{step === "production" ? tr("Ready for invoices") : tr("Step {n} of 4", { n: Math.min(at + 1, 4) })}</Badge>}>
        <ol className="flex flex-col gap-3">
          {stepItems.map((s, i) => {
            const done = at > i;
            const current = at === i;
            return (
              <li key={s.key} className={`rounded-xl p-3 ring-1 ring-inset ${current ? "ring-[color:var(--fb-v2-accent)]" : "ring-[color:var(--fb-v2-border)]"}`} aria-current={current ? "step" : undefined}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-medium">{i + 1}. {s.title}</h3>
                  {done ? <Badge tone="good">{tr("Done")}</Badge> : null}
                </div>
                <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">{s.body}</p>
                {current && s.key === "key" ? (
                  <Button disabled={!!busy || !meta.secrets_available} onClick={() => run("key", () => api.post(`/orgs/${orgId}/einvoice/zatca/key`), tr("Key and CSR created."))}>{tr("Create key and CSR")}</Button>
                ) : null}
                {current && s.key === "compliance" ? (
                  <div className="flex flex-wrap items-end gap-2">
                    <Field label={tr("OTP from the Fatoora portal")}>
                      <input className={`${input} w-40`} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" dir="ltr" autoComplete="one-time-code" />
                    </Field>
                    <Button className="mb-4" disabled={!!busy || otp.length !== 6} onClick={() => run("compliance", () => api.post(`/orgs/${orgId}/einvoice/zatca/compliance`, { otp }), tr("Compliance certificate received."))}>{tr("Get certificate")}</Button>
                  </div>
                ) : null}
                {current && s.key === "checks" ? (
                  <Button disabled={!!busy} onClick={() => run("checks", () => api.post(`/orgs/${orgId}/einvoice/zatca/checks`), tr("Checks finished."))}>{busy === "checks" ? tr("Checking…") : tr("Run checks")}</Button>
                ) : null}
                {current && s.key === "production" ? (
                  <Button disabled={!!busy} onClick={() => run("production", () => api.post(`/orgs/${orgId}/einvoice/zatca/production`), tr("Production certificate received."))}>{tr("Get production certificate")}</Button>
                ) : null}
                {s.key === "checks" && profile?.compliance_results?.length ? (
                  <ul className="mt-2 flex flex-wrap gap-1">
                    {profile.compliance_results.map((r, n) => (
                      <li key={n}><Badge tone={r.ok ? "good" : "bad"}>{`${r.type} · ${r.kind} · ${r.status || r.http_status}`}</Badge></li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ol>
        {!meta.secrets_available ? <Notice kind="error">{tr("The server has no encryption key, so the unit's private key can't be stored. Ask your operator to set CREDENTIALS_ENCRYPTION_KEY.")}</Notice> : null}
        {profile?.onboarding_error ? <Notice kind="error">{tr(profile.onboarding_error)}</Notice> : null}
        {profile?.certificate_expires_at ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Certificate valid until {date}", { date: when(profile.certificate_expires_at) })}</p> : null}
        {at > 0 ? (
          <Button variant="danger" className="mt-2" disabled={!!busy} onClick={() => window.confirm(tr("Reset onboarding? The key and certificates are deleted. The invoice counter and hash chain stay.")) && run("reset", () => api.post(`/orgs/${orgId}/einvoice/zatca/reset`), tr("Onboarding reset."))}>
            {tr("Reset onboarding")}
          </Button>
        ) : null}
      </Section>
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
    </div>
  );
}

export function EgyptSettings({ orgId, meta, onChange }: { orgId: string; meta: Meta; onChange: () => void }) {
  const tr = useTr();
  const profile = meta.profiles.EG;
  const { form, set } = useProfileForm(profile, EG_KEYS);
  const [secret, setSecret] = useState("");
  const [signerToken, setSignerToken] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);

  async function run(key: string, fn: () => Promise<unknown>, ok: string | ((r: unknown) => string)) {
    setBusy(key);
    setMsg(null);
    try {
      const r = await fn();
      setMsg({ kind: "ok", text: typeof ok === "string" ? ok : ok(r) });
      onChange();
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  function save() {
    const body: Record<string, unknown> = { ...form, environment: form.environment || "preprod", signer_mode: form.signer_mode || "manual" };
    if (form.client_id === "") delete body.client_id;
    if (secret) body.client_secret = secret;
    if (signerToken) body.signer_token = signerToken;
    run("save", async () => {
      await api.put(`/orgs/${orgId}/einvoice/settings/EG`, body);
      setSecret("");
      setSignerToken("");
    }, tr("Saved."));
  }

  return (
    <div className="flex flex-col gap-2">
      {profile?.simulated ? <Notice>{tr("Demo: answers from the ETA are simulated. Nothing is sent.")}</Notice> : null}
      <Section title={tr("Issuer")}>
        <div className="grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          <TextInput label={tr("Legal name")} value={form.seller_name} onChange={set("seller_name")} />
          <TextInput label={tr("Legal name in Arabic")} value={form.seller_name_ar} onChange={set("seller_name_ar")} />
          <TextInput label={tr("Tax registration number")} value={form.tax_number} onChange={set("tax_number")} hint={tr("9 digits")} ltr max={9} />
          <TextInput label={tr("Branch ID")} value={form.registration_id} onChange={set("registration_id")} hint={tr("0 if you have one branch")} ltr max={10} />
          <TextInput label={tr("Activity code")} value={form.activity_code} onChange={set("activity_code")} hint={tr("4 digits, from your ETA profile")} ltr max={4} />
          <TextInput label={tr("Governorate")} value={form.region} onChange={set("region")} />
          <TextInput label={tr("City")} value={form.city} onChange={set("city")} />
          <TextInput label={tr("Street")} value={form.street} onChange={set("street")} />
          <TextInput label={tr("Building number")} value={form.building_number} onChange={set("building_number")} ltr max={20} />
          <TextInput label={tr("Postal code")} value={form.postal_code} onChange={set("postal_code")} ltr max={10} />
        </div>
      </Section>
      <Section title={tr("ETA connection")}>
        <div className="grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={tr("Environment")}>
            <select className={input} value={form.environment || "preprod"} onChange={(e) => set("environment")(e.target.value)}>
              <option value="preprod">{tr("Pre-production")}</option>
              <option value="production">{tr("Production")}</option>
            </select>
          </Field>
          <TextInput label={tr("Client ID")} value={form.client_id} onChange={set("client_id")} ltr max={100} hint={tr("From the ETA portal: Taxpayer profile, ERP registration.")} />
          <TextInput
            label={tr("Client secret")}
            value={secret}
            onChange={setSecret}
            type="password"
            ltr
            placeholder={profile?.client_secret_set ? tr("Saved ({hint}). Type to replace.", { hint: profile.client_secret_hint || "…" }) : ""}
            hint={tr("Stored encrypted. Never shown again.")}
          />
        </div>
        <fieldset className="mb-4">
          <legend className="mb-1 text-sm font-medium">{tr("Who signs")}</legend>
          <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("The ETA only accepts invoices signed with your company's USB token or HSM. FloBrain never signs for you.")}</p>
          {(["manual", "external"] as const).map((mode) => (
            <label key={mode} className="flex items-start gap-2 text-sm">
              <input type="radio" name="signer_mode" className="mt-1" checked={(form.signer_mode || "manual") === mode} onChange={() => set("signer_mode")(mode)} />
              <span>
                <span className="block font-medium">{mode === "manual" ? tr("Manual") : tr("Signer service on your premises")}</span>
                <span className="text-[color:var(--fb-v2-text-muted)]">
                  {mode === "manual" ? tr("Download the text to sign, sign it with your token, paste the signature.") : tr("A small service next to the token signs when an approved invoice is sent. Its address must be on the server's allowed list.")}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        {form.signer_mode === "external" ? (
          <div className="grid gap-x-4 sm:grid-cols-2">
            <TextInput label={tr("Signer address (https)")} value={form.signer_url} onChange={set("signer_url")} ltr max={300} />
            <TextInput
              label={tr("Signer access token")}
              value={signerToken}
              onChange={setSignerToken}
              type="password"
              ltr
              placeholder={profile?.signer_token_set ? tr("Saved ({hint}). Type to replace.", { hint: profile.signer_token_hint || "…" }) : ""}
            />
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button onClick={save} disabled={!!busy}>{busy === "save" ? tr("Saving…") : tr("Save")}</Button>
          <Button
            variant="outline"
            disabled={!!busy || !profile?.client_secret_set}
            onClick={() => run("check", () => api.post<{ ok: boolean; error?: string }>(`/orgs/${orgId}/einvoice/eta/check`), (r) => ((r as { ok: boolean }).ok ? tr("The ETA accepted the client ID and secret.") : tr("The ETA did not accept them.")))}
          >
            {tr("Check connection")}
          </Button>
        </div>
      </Section>
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
    </div>
  );
}
