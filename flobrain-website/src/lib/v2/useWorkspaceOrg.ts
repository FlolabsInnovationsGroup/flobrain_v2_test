"use client";

import { useEffect, useState } from "react";

import { v2Client } from "@/lib/v2/client";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";

export function useWorkspaceOrg(slug: string) {
  const [orgId, setOrgId] = useState<string | null>(null);
  // The state is tagged with the slug it was resolved for; a different slug reads as "loading" until it resolves.
  const [result, setResult] = useState<{ slug: string | null; state: ScreenState }>({ slug: null, state: "loading" });
  const [error, setError] = useState<string | null>(null);
  const state: ScreenState = result.slug === slug ? result.state : "loading";

  useEffect(() => {
    let cancelled = false;
    v2Client()
      .orgs(slug)
      .then((orgs) => {
        if (cancelled) return;
        const match = orgs.find((org) => org.slug === slug) ?? orgs[0];
        if (!match) {
          setResult({ slug, state: "no-access" });
          return;
        }
        setOrgId(match.id);
        setResult({ slug, state: "ready" });
      })
      .catch((err: { response?: { status?: number } }) => {
        if (cancelled) return;
        setError("Could not load workspace");
        setResult({ slug, state: screenStateFromHttp(err.response?.status ?? 500) });
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  return { orgId, state, error };
}
