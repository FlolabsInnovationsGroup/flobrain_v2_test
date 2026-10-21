"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import { contactVisible, filterDirectory, type DirectoryMember } from "@/lib/v2/screens/directory";
import { isEmptyList, screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function DirectoryScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [query, setQuery] = useState("");
  const [members, setMembers] = useState<DirectoryMember[]>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .members(orgId)
      .then((data) => {
        const rows = (data.results ?? []) as DirectoryMember[];
        setMembers(rows);
        setState(screenStateFromHttp(200, isEmptyList(data)));
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load directory");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  const visible = useMemo(() => filterDirectory(members, query), [members, query]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Directory</h1>
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search members"
        className="mb-4 w-full max-w-sm rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-2 py-1"
      />
      <ScreenBody state={state} error={error || orgError} emptyLabel="No members yet" onRetry={load}>
        <ul className="space-y-2">
          {visible.map((member) => (
            <li key={member.id}>
              <Link href={`/w/${orgSlug}/members/${member.id}`} className="text-[color:var(--fb-v2-accent)]">
                {member.username || member.id}
              </Link>
              {contactVisible(member) ? (
                <span className="ms-2 text-sm text-[color:var(--fb-v2-text-muted)]">{member.email}</span>
              ) : null}
            </li>
          ))}
        </ul>
      </ScreenBody>
    </section>
  );
}
