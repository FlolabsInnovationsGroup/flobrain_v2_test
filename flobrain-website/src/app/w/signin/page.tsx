"use client";

import { Rocket } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { DemoPicker } from "@/components/v2/demo/DemoPicker";
import { AuroraHorizon } from "@/components/v2/shell/AuroraHorizon";
import { BrandMark } from "@/components/v2/shell/BrandMark";
import { Notice } from "@/components/v2/ui/kit";
import { Button } from "@/components/v2/ui/button";
import { dirFor, t, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { api, apiError } from "@/lib/v2/api";
import { homePath, safeNext } from "@/lib/v2/home";
import { v2Client } from "@/lib/v2/client";
import { newClientNonce } from "@/lib/v2/sso";
import "@/styles/v2-tokens.css";

/** A still from the cockpit: what someone sees after signing back in. Decorative only. */
function CockpitGlimpse() {
  const tr = useTr();
  return (
    <aside
      aria-hidden
      className="relative m-3 hidden overflow-hidden rounded-3xl bg-[color:var(--fb-v2-void)] ring-1 ring-inset ring-[color:var(--fb-v2-border)] lg:block"
    >
      <AuroraHorizon top="58%" size={1800} />
      <div className="absolute inset-x-[8%] top-[12%] flex flex-col gap-3">
        <p className="self-end rounded-2xl rounded-ee-md bg-[linear-gradient(135deg,#2a2350,#221d3f)] px-4 py-2.5 text-[15px] ring-1 ring-inset ring-[color:rgba(124,107,255,.35)]">
          {tr("What did I miss while I was out?")}
        </p>
        <div className="flex gap-3">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-[linear-gradient(135deg,#a855f7,#cc34ff)] text-white">
            <Rocket size={16} strokeWidth={2} />
          </span>
          <p className="rounded-2xl rounded-ss-md bg-[color:var(--fb-v2-surface)] px-4 py-3 text-[15px] leading-relaxed ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
            {tr("Three things. The launch date is set, Sara shipped the screenshots, and one task waits for your approval.")}
          </p>
        </div>
        <div className="ms-11 rounded-2xl bg-[linear-gradient(180deg,rgba(255,181,71,.10),rgba(255,181,71,.03))] p-4 ring-1 ring-inset ring-[color:rgba(255,181,71,.35)]">
          <p className="v2-mono text-[11px] font-semibold text-[color:var(--fb-v2-waiting)]">{tr("Needs your approval")}</p>
          <p className="mt-1.5 text-[15px] font-medium">{tr("Order an Android test device for Omar")}</p>
        </div>
      </div>
      <p className="v2-mono absolute inset-x-0 bottom-9 text-center text-xs tracking-[0.08em] text-[#c9c0ff]">LIVE LONG AND PROSPER</p>
    </aside>
  );
}

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

  const field = "v2-input mt-1.5 h-12 rounded-xl px-3.5 text-[15px]";
  return (
    <div className="v2-root grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]" dir={dirFor(locale)}>
      <main className="flex flex-col px-5 py-7 sm:px-10 lg:px-16">
        <Link href="/v2" className="flex w-fit items-center gap-2.5 text-lg">
          <BrandMark size={28} />
          <span className="font-semibold tracking-tight">FloBrain</span>
        </Link>
        <div className="mx-auto my-10 flex w-full max-w-[440px] flex-1 flex-col justify-center">
          <h1 className="text-[clamp(34px,4vw,46px)] font-semibold leading-[1.02] tracking-[-0.045em]">{t(locale, "auth.signin")}</h1>
          <p className="mt-3 text-base leading-relaxed text-[color:var(--fb-v2-text-muted)]">
            {tr("Your rooms, meetings and buddies are right where you left them.")}
          </p>
          <form method="post" onSubmit={onSubmit} className="mt-8">
            <label className="block text-[13px] font-medium text-[color:var(--fb-v2-text-muted)]">
              {t(locale, "auth.email")}
              <input className={field} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label className="mt-4 block text-[13px] font-medium text-[color:var(--fb-v2-text-muted)]">
              {t(locale, "auth.password")}
              <input className={field} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <Link href="/w/reset-password" className="mt-2 block w-fit text-[13px] text-[color:var(--fb-v2-accent)] hover:underline">
              {t(locale, "auth.forgot")}
            </Link>
            {error ? (
              <div className="mt-4">
                <Notice kind="error">{error}</Notice>
              </div>
            ) : null}
            <button
              type="submit"
              disabled={busy || !password}
              className="mt-6 h-12 w-full rounded-xl bg-[#f4f2fb] text-[15px] font-semibold text-[#0b0a12] shadow-[0_12px_30px_-12px_rgba(169,155,255,.7)] transition-colors hover:bg-white disabled:opacity-50"
            >
              {t(locale, "auth.submit")}
            </button>
            <Button type="button" variant="outline" className="mt-2.5 h-12 w-full rounded-xl text-[15px]" onClick={onSso}>
              {tr("Sign in with SSO")}
            </Button>
          </form>
          <DemoPicker />
        </div>
        <p className="text-[13px] text-[color:var(--fb-v2-text-faint)]">© 2026 FloLabs Innovations Group</p>
      </main>
      <CockpitGlimpse />
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
