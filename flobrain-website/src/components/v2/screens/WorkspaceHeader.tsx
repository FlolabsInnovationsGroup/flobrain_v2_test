"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { TopBarTimer } from "@/components/v2/timer/TopBarTimer";
import { v2Client } from "@/lib/v2/client";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function WorkspaceHeader({ orgSlug }: { orgSlug: string }) {
  const { orgId } = useWorkspaceOrg(orgSlug);
  const router = useRouter();
  const [orgs, setOrgs] = useState<Array<{ slug: string; name: string }>>([]);

  useEffect(() => {
    v2Client()
      .orgs()
      .then((rows) => setOrgs(rows))
      .catch(() => undefined);
  }, []);

  return (
    <header className="flex items-center justify-between border-b border-[color:var(--fb-v2-border)] px-4 py-3">
      <label className="text-sm text-[color:var(--fb-v2-text-muted)]">
        Workspace
        <select
          className="ms-2 bg-transparent"
          aria-label="Workspace"
          value={orgSlug}
          onChange={(event) => router.push(`/w/${event.target.value}`)}
        >
          {orgs.length === 0 ? <option value={orgSlug}>{orgSlug}</option> : null}
          {orgs.map((org) => (
            <option key={org.slug} value={org.slug}>
              {org.name}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-center gap-3">
        <Link href={`/w/${orgSlug}/search`} className="text-sm">
          Search
        </Link>
        <Link href={`/w/${orgSlug}/notifications`} className="text-sm">
          Inbox
        </Link>
        <TopBarTimer orgId={orgId} />
      </div>
    </header>
  );
}
