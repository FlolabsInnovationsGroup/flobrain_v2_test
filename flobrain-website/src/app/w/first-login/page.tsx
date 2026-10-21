"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { dirFor, t, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { api, apiError } from "@/lib/v2/api";
import { storeV2Tokens, v2Client, type V2TokenPair } from "@/lib/v2/client";
import { normalizePhone } from "@/lib/v2/screens/people";
import "@/styles/v2-tokens.css";

/** The backend's field errors ({"password": ["…"]}) as one sentence. */
function readable(details: string): string {
  try {
    const parsed = JSON.parse(details) as Record<string, string[] | string>;
    return Object.values(parsed).flat().join(" ");
  } catch {
    return details;
  }
}

/** Decision 10: the first sign-in sets a new password and a phone number, then opens the cockpit. */
export default function FirstLoginPage() {
  const router = useRouter();
  const locale = useLocale();
  const tr = useTr();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cleanPhone = normalizePhone(phone);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (password !== confirm) {
      setError(tr("The two passwords are different."));
      return;
    }
    if (!cleanPhone) {
      setError(tr("Enter the number with its country code, like +20 100 123 4567"));
      return;
    }
    setBusy(true);
    try {
      storeV2Tokens(await api.post<V2TokenPair>("/auth/first-login", { password, phone: cleanPhone }));
      const orgs = await v2Client().orgs().catch(() => []);
      router.replace(orgs[0] ? `/w/${orgs[0].slug}` : "/w/flolabs");
    } catch (err) {
      const { status, details } = apiError(err);
      setError(status === 400 && details ? readable(details) : tr("Could not update password"));
      setBusy(false);
    }
  }

  const input = "mt-1 w-full rounded-[length:var(--fb-v2-radius)] bg-transparent px-3 py-2 ring-1 ring-[color:var(--fb-v2-border)]";
  return (
    <div className="v2-root flex min-h-dvh items-center justify-center px-4" dir={dirFor(locale)}>
      <form onSubmit={onSubmit} className="w-full max-w-sm rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-surface)] p-6">
        <h1 className="mb-1 text-xl font-semibold">{t(locale, "auth.firstLogin")}</h1>
        <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Choose your own password and add a phone number your team can reach you on.")}</p>
        <label className="mb-4 block text-sm">
          {t(locale, "auth.newPassword")}
          <input className={input} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <label className="mb-4 block text-sm">
          {tr("Type it again")}
          <input className={input} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </label>
        <label className="mb-1 block text-sm">
          {tr("Phone number")}
          <input
            className={input}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+20 100 123 4567"
            value={phone}
            aria-invalid={phone !== "" && !cleanPhone}
            aria-describedby="phone-hint"
            onChange={(e) => setPhone(e.target.value)}
            required
          />
        </label>
        <p id="phone-hint" className="mb-4 text-xs text-[color:var(--fb-v2-text-muted)]">
          {phone !== "" && !cleanPhone ? tr("Start with + and the country code.") : tr("With the country code. Only admins and people with contact access see it.")}
        </p>
        {error ? (
          <p role="alert" className="mb-3 text-[color:var(--fb-v2-error)]">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="w-full" disabled={busy}>
          {t(locale, "auth.submit")}
        </Button>
      </form>
    </div>
  );
}
