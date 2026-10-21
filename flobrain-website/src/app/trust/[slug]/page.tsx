"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { TrustView } from "@/components/v2/compliance/TrustView";
import type { TrustPublic } from "@/components/v2/compliance/types";
import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { getApiBaseUrl } from "@/lib/axios";
import "@/styles/v2-tokens.css";

/**
 * Public trust page, signed out. Reads ``GET /api/v2/public/trust/<slug>``: only the sections the org
 * published. Not published (or the feature is off) is a plain "not found".
 */
export default function TrustPage() {
  const { slug } = useParams<{ slug: string }>();
  const locale = useLocale();
  const tr = useTr();
  const [data, setData] = useState<TrustPublic | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "failed">("loading");
  const base = `${getApiBaseUrl()}/api/v2/public/trust/${encodeURIComponent(slug)}`;

  useEffect(() => {
    let alive = true;
    fetch(base, { cache: "no-store" })
      .then((res) => {
        if (res.status === 404) return Promise.reject("missing");
        return res.ok ? res.json() : Promise.reject("failed");
      })
      .then((value: TrustPublic) => {
        if (!alive) return;
        setData(value);
        setState("ready");
        document.title = value.headline;
      })
      .catch((why) => alive && setState(why === "missing" ? "missing" : "failed"));
    return () => {
      alive = false;
    };
  }, [base]);

  async function request(body: Record<string, unknown>) {
    try {
      const res = await fetch(`${base}/requests`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      return res.status;
    } catch {
      return 0;
    }
  }

  return (
    <div className="v2-root min-h-dvh px-4 py-8 sm:px-6" dir={dirFor(locale)}>
      <main className="mx-auto w-full max-w-4xl">
        {state === "ready" && data ? (
          <TrustView data={data} onRequest={request} />
        ) : state === "missing" ? (
          <p role="alert">{tr("This trust page is not published.")}</p>
        ) : state === "failed" ? (
          <p role="alert">{tr("The page could not be loaded. Try again in a minute.")}</p>
        ) : (
          <p role="status">{tr("Loading…")}</p>
        )}
      </main>
    </div>
  );
}
