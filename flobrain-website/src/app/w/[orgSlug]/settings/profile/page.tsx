"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Field, Notice, PageHeader, Section } from "@/components/v2/ui/kit";
import { LOCALES, setLocale, type V2Locale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { normalizePhone } from "@/lib/v2/screens/people";
import { useOrgData } from "@/lib/v2/useOrgData";

type Me = {
  id: string;
  email: string;
  username: string | null;
  phone: string | null;
  timezone: string | null;
  locale: string;
  about_me: string | null;
  discord_handle: string | null;
  linkedin_url: string | null;
};

function timeZones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

export default function ProfilePage() {
  const tr = useTr();
  const { orgId } = useAccess();
  const me = useOrgData<Me>(orgId, "/me", { orgScoped: false });
  return (
    <div className="max-w-2xl">
      <PageHeader title={tr("My profile")} intro={tr("How you appear in the directory. Your email and role are set by your organization.")} />
      <ScreenBody state={me.state} error={me.error} onRetry={me.reload}>
        {me.data ? <ProfileForm key={me.data.id} me={me.data} onSaved={me.reload} /> : null}
      </ScreenBody>
    </div>
  );
}

function ProfileForm({ me, onSaved }: { me: Me; onSaved: () => void }) {
  const tr = useTr();
  const { access } = useAccess();
  const locked = !!access?.demo_role;
  const [form, setForm] = useState({
    username: me.username ?? "",
    phone: me.phone ?? "",
    timezone: me.timezone ?? "",
    locale: me.locale || "en",
    about_me: me.about_me ?? "",
    discord_handle: me.discord_handle ?? "",
    linkedin_url: me.linkedin_url ?? "",
  });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [resetSent, setResetSent] = useState(false);
  const zones = timeZones();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));
  const phoneOk = !form.phone || normalizePhone(form.phone) !== null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    if (!phoneOk) {
      setMessage({ kind: "error", text: tr("Enter the number with its country code, like +20 100 123 4567") });
      return;
    }
    const body: Record<string, string> = { ...form, phone: normalizePhone(form.phone) ?? "" };
    if (!body.phone) delete body.phone;
    try {
      await api.patch("/me", body);
      if (form.locale !== me.locale && LOCALES.some((l) => l.code === form.locale)) setLocale(form.locale as V2Locale);
      setMessage({ kind: "ok", text: tr("Profile saved.") });
      onSaved();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function sendReset() {
    try {
      await api.post("/auth/password/forgot", { email: me.email });
      setResetSent(true);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <>
      {locked ? <Notice>{tr("This is a demo profile, so it can't be changed.")}</Notice> : null}
      <form onSubmit={save}>
        <fieldset disabled={locked}>
          <Field label={tr("Name")}>
            <input className="v2-input" value={form.username} onChange={set("username")} required maxLength={150} />
          </Field>
          <Field label={tr("Email")} hint={tr("Ask an admin to change it.")}>
            <input className="v2-input" value={me.email} readOnly disabled />
          </Field>
          <Field label={tr("Phone")} hint={tr("With the country code. Only admins and people with contact access see it.")}>
            <input className="v2-input" type="tel" inputMode="tel" value={form.phone} onChange={set("phone")} aria-invalid={!phoneOk} placeholder="+20 100 123 4567" />
          </Field>
          <div className="grid gap-x-4 md:grid-cols-2">
            <Field label={tr("Time zone")}>
              {zones.length ? (
                <select className="v2-input" value={form.timezone} onChange={set("timezone")}>
                  <option value="">{tr("Not set")}</option>
                  {zones.map((z) => (
                    <option key={z} value={z}>
                      {z}
                    </option>
                  ))}
                </select>
              ) : (
                <input className="v2-input" value={form.timezone} onChange={set("timezone")} placeholder="Africa/Cairo" />
              )}
            </Field>
            <Field label={tr("Language")}>
              <select className="v2-input" value={form.locale} onChange={set("locale")}>
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code} lang={l.code}>
                    {l.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label={tr("About me")}>
            <textarea className="v2-input" rows={4} maxLength={2000} value={form.about_me} onChange={set("about_me")} />
          </Field>
          <div className="grid gap-x-4 md:grid-cols-2">
            <Field label={tr("Discord")}>
              <input className="v2-input" value={form.discord_handle} onChange={set("discord_handle")} maxLength={100} />
            </Field>
            <Field label={tr("LinkedIn")}>
              <input className="v2-input" type="url" value={form.linkedin_url} onChange={set("linkedin_url")} placeholder="https://www.linkedin.com/in/…" />
            </Field>
          </div>
          <Button type="submit">{tr("Save profile")}</Button>
        </fieldset>
      </form>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      <Section title={tr("Password")}>
        {locked ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Demo accounts have no password.")}</p>
        ) : resetSent ? (
          <Notice kind="ok">{tr("Check {email} for a link to set a new password. It works for an hour.", { email: me.email })}</Notice>
        ) : (
          <>
            <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("We email you a link to set a new password. Other devices are signed out when you change it.")}</p>
            <Button variant="outline" onClick={sendReset}>
              {tr("Email me a password link")}
            </Button>
          </>
        )}
      </Section>
    </>
  );
}
