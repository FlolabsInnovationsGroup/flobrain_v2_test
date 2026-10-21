"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { DemoPicker } from "@/components/v2/demo/DemoPicker";
import { Notice } from "@/components/v2/ui/kit";
import { Button } from "@/components/v2/ui/button";
import { dirFor, t, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { api, apiError } from "@/lib/v2/api";
import { homePath, safeNext } from "@/lib/v2/home";
import { v2Client } from "@/lib/v2/client";
import { newClientNonce } from "@/lib/v2/sso";
import "@/styles/v2-tokens.css";

function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const locale = useLocale();
  const tr = useTr();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const tokens = await v2Client().signin(email, password);
      if (tokens.must_change_password) {
        router.replace("/w/first-login");
        return;
      }
      router.replace(safeNext(params.get("next")) ?? (await homePath()));
    } catch (err) {
      const e = apiError(err);
      setError(e.code === "sso_required" ? tr("Your organization signs in with SSO. Use the button below.") : tr("That email and password don't match."));
      setBusy(false);
    }
  }

  async function onSso() {
    setError("");
    if (!email) {
      setError(tr("Enter your work email first."));
      return;
    }
    try {
      const res = await api.get<{ authorize_url: string }>("/sso/start", { email, client_nonce: newClientNonce() });
      window.location.href = res.authorize_url;
    } catch {
      setError(tr("There is no SSO set up for this email's domain."));
    }
  }

  return (
    <div className="v2-root min-h-dvh px-4 py-10 md:px-10" dir={dirFor(locale)}>
      <div className="mx-auto flex max-w-6xl flex-col gap-12 lg:flex-row lg:items-start">
        <form
          method="post"
          onSubmit={onSubmit}
          className="w-full max-w-sm shrink-0 rounded-xl bg-[color:var(--fb-v2-surface)] p-6 ring-1 ring-inset ring-[color:var(--fb-v2-border)]"
        >
          <p className="mb-6 text-sm font-semibold text-[color:var(--fb-v2-accent)]">FloBrain</p>
          <h1 className="mb-5 text-2xl font-semibold tracking-tight">{t(locale, "auth.signin")}</h1>
          <label className="mb-3 block text-sm">
            {t(locale, "auth.email")}
            <input className="v2-input mt-1" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label className="mb-4 block text-sm">
            {t(locale, "auth.password")}
            <input
              className="v2-input mt-1"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error ? <Notice kind="error">{error}</Notice> : null}
          <Button type="submit" className="w-full" disabled={busy || !password}>
            {t(locale, "auth.submit")}
          </Button>
          <Button type="button" variant="outline" className="mt-2 w-full" onClick={onSso}>
            {tr("Sign in with SSO")}
          </Button>
          <Link href="/w/reset-password" className="mt-4 block text-sm text-[color:var(--fb-v2-text-muted)] hover:underline">
            {t(locale, "auth.forgot")}
          </Link>
        </form>
        <DemoPicker />
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense>
      <SignInForm />
    </Suspense>
  );
}
