"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import { accessListsEmpty, activeGrants, pendingRequests, type AccessGrant, type AccessRequest } from "@/lib/v2/screens/access";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function AccessScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    Promise.all([v2Client().permissionRequests(orgId), v2Client().grants(orgId)])
      .then(([reqData, grantData]) => {
        const nextRequests = (reqData.results ?? []) as AccessRequest[];
        const nextGrants = (grantData.results ?? []) as AccessGrant[];
        setRequests(nextRequests);
        setGrants(nextGrants);
        setState(accessListsEmpty(nextRequests, nextGrants) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load access settings");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Access requests</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No requests or grants yet" onRetry={load}>
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Requests</h2>
            <ul className="space-y-2">
              {pendingRequests(requests).map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-2">
                  <span>
                    {row.perm_key}
                    {row.reason ? ` · ${row.reason}` : ""}
                  </span>
                  <span className="flex gap-1">
                    <Button type="button" onClick={() => orgId && v2Client().decideRequest(orgId, row.id, "approve").then(load)}>
                      Approve
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => orgId && v2Client().decideRequest(orgId, row.id, "reject").then(load)}
                    >
                      Reject
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Grants</h2>
            <ul className="space-y-2">
              {activeGrants(grants).map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-2">
                  <span>{row.perm_key}</span>
                  <Button type="button" variant="ghost" onClick={() => orgId && v2Client().revokeGrant(orgId, row.id).then(load)}>
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </ScreenBody>
    </section>
  );
}
