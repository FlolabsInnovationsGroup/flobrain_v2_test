"use client";

import { useEffect, useState } from "react";

import { v2Client } from "@/lib/v2/client";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";

export function useWorkspaceOrg(slug: string) {
  const [orgId, setOrgId] = useState<string | null>(null);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    v2Client()
      .orgs(slug)
      .then((orgs) => {
        if (cancelled) return;
        const match = orgs.find((org) => org.slug === slug) ?? orgs[0];
        if (!match) {
          setState("no-access");
          return;
        }
        setOrgId(match.id);
        setState("ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        if (cancelled) return;
        setError("Could not load workspace");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  return { orgId, state, error };
}
