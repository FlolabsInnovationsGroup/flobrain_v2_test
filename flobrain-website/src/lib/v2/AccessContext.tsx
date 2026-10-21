"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { api } from "./api";
import type { Access } from "./access";
import { useWorkspaceOrg } from "./useWorkspaceOrg";

type Ctx = { access: Access | null; orgId: string | null; reload: () => void };
const AccessCtx = createContext<Ctx>({ access: null, orgId: null, reload: () => undefined });

export function AccessProvider({ orgSlug, children }: { orgSlug: string; children: React.ReactNode }) {
  const { orgId } = useWorkspaceOrg(orgSlug);
  const [access, setAccess] = useState<Access | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!orgId) return;
    let cancelled = false;
    api
      .get<Access>(`/orgs/${orgId}/me/access`)
      .then((value) => !cancelled && setAccess(value))
      .catch(() => !cancelled && setAccess(null));
    return () => {
      cancelled = true;
    };
  }, [orgId, tick]);

  return <AccessCtx.Provider value={{ access, orgId, reload: () => setTick((n) => n + 1) }}>{children}</AccessCtx.Provider>;
}

export function useAccess() {
  return useContext(AccessCtx);
}
