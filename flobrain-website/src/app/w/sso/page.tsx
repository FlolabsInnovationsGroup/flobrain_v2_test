"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Notice } from "@/components/v2/ui/kit";
import { api } from "@/lib/v2/api";
import { storeV2Tokens, type V2TokenPair } from "@/lib/v2/client";
import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { homePath } from "@/lib/v2/home";
import { SSO_ERRORS, takeClientNonce } from "@/lib/v2/sso";
import "@/styles/v2-tokens.css";

function SsoReturn() {
  const params = useSearchParams();
  const router = useRouter();
  const tr = useTr();
  const locale = useLocale();
  const failure = params.get("error");
  const [error, setError] = useState(failure ? (SSO_ERRORS[failure] ?? "SSO sign-in failed.") : "");

  useEffect(() => {
    const code = params.get("code");
    if (!code || failure) return;
    api
      .post<V2TokenPair>("/sso/exchange", { code, client_nonce: takeClientNonce() })
      .then((tokens) => {
        storeV2Tokens(tokens);
        return homePath().then((path) => router.replace(path));
      })
      .catch(() => setError("This sign-in can only finish in the browser that started it. Start again."));
  }, [params, failure, router]);

  return (
    <div dir={dirFor(locale)} className="v2-root flex min-h-dvh items-center justify-center p-6">
      <div className="max-w-sm">
        <h1 className="mb-2 text-xl font-semibold">{tr("Signing you in")}</h1>
        {error ? (
          <>
            <Notice kind="error">{tr(error)}</Notice>
            <Link className="text-sm underline" href="/w/signin">
              {tr("Back to sign in")}
            </Link>
          </>
        ) : (
          <Notice>{tr("Checking with your identity provider…")}</Notice>
        )}
      </div>
    </div>
  );
}

export default function SsoPage() {
  return (
    <Suspense>
      <SsoReturn />
    </Suspense>
  );
}
