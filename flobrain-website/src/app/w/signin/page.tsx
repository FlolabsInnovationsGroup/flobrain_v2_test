"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { dirFor, getLocale, t } from "@/i18n";
import { v2Client } from "@/lib/v2/client";
import "@/styles/v2-tokens.css";

function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const locale = getLocale();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const tokens = await v2Client().signin(email, password);
      if (tokens.must_change_password) {
        router.replace("/w/first-login");
        return;
      }
      router.replace(params.get("next") || "/w/flolabs");
    } catch {
      setError("Invalid credentials");
    }
  }

  return (
    <div className="v2-root flex min-h-dvh items-center justify-center" dir={dirFor(locale)}>
      <form
        method="post"
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-surface)] p-6"
      >
        <h1 className="mb-4 text-xl font-semibold">{t(locale, "auth.signin")}</h1>
        <label className="mb-3 block text-sm">
          {t(locale, "auth.email")}
          <input
            className="mt-1 w-full rounded-[length:var(--fb-v2-radius)] bg-transparent px-3 py-2 ring-1 ring-[color:var(--fb-v2-border)]"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="mb-4 block text-sm">
          {t(locale, "auth.password")}
          <input
            className="mt-1 w-full rounded-[length:var(--fb-v2-radius)] bg-transparent px-3 py-2 ring-1 ring-[color:var(--fb-v2-border)]"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error ? <p className="mb-3 text-[color:var(--fb-v2-error)]">{error}</p> : null}
        <Button type="submit" className="w-full">
          {t(locale, "auth.submit")}
        </Button>
      </form>
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
