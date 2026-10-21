"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import type { DirectoryMember } from "@/lib/v2/screens/directory";
import { canViewMemberProfile, profileHeadline } from "@/lib/v2/screens/memberProfile";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function MemberProfileScreen({ orgSlug, userId }: { orgSlug: string; userId: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [member, setMember] = useState<DirectoryMember | null>(null);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .member(orgId, userId)
      .then((data) => {
        const row = data as DirectoryMember;
        setMember(row);
        setState(canViewMemberProfile(row, false) ? "ready" : "no-access");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load member");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, userId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Member</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="Member not found" onRetry={load}>
        {member ? (
          <div>
            <p className="text-lg">{profileHeadline(member)}</p>
            <p className="text-[color:var(--fb-v2-text-muted)]">{member.employment_status}</p>
            {member.email ? <p>{member.email}</p> : null}
            {member.teams?.length ? <p>Teams: {member.teams.join(", ")}</p> : null}
          </div>
        ) : null}
      </ScreenBody>
    </section>
  );
}
