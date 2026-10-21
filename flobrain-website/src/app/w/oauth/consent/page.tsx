"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ConsentScreen } from "@/components/v2/mcp/ConsentScreen";
import { Loading } from "@/components/v2/states";
import { dirFor, useLocale } from "@/i18n";
import { v2Client } from "@/lib/v2/client";
import "@/styles/v2-tokens.css";

/**
 * OAuth consent for apps connecting to FloBrain's MCP server (growth round M1). The API's
 * ``/oauth/authorize`` sends the browser here with a signed request. Signed-out people go to
 * sign-in first and come back to this exact address.
 */
function Consent() {
  const router = useRouter();
  const params = useSearchParams();
  const [ready, setReady] = useState(false);
  const request = params.get("request") ?? "";
  const error = params.get("error") ?? "";

  useEffect(() => {
    if (error) return; // nothing to approve: show the problem without asking to sign in
    let cancelled = false;
    v2Client()
      .me()
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        const back = `${window.location.pathname}${window.location.search}`;
        router.replace(`/w/signin?next=${encodeURIComponent(back)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [router, error]);

  if (error) return <ConsentScreen request="" error={error} />;
  if (!ready) return <Loading />;
  return <ConsentScreen request={request} error={request ? "" : "invalid"} />;
}

export default function OAuthConsentPage() {
  const locale = useLocale();
  return (
    <div className="v2-root min-h-dvh" dir={dirFor(locale)}>
      <Suspense fallback={<Loading />}>
        <Consent />
      </Suspense>
    </div>
  );
}
