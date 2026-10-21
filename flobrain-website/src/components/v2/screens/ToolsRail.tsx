"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { v2Client } from "@/lib/v2/client";
import { impactScoreLabel } from "@/lib/v2/screens/metrics";
import { toolsEmpty, type ToolRow } from "@/lib/v2/screens/tools";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function ToolsRail({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [tools, setTools] = useState<ToolRow[]>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .tools(orgId)
      .then((rows) => {
        const next = rows as ToolRow[];
        setTools(next);
        setState(toolsEmpty(next) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load tools");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <aside className="hidden w-72 border-s border-[color:var(--fb-v2-border)] p-4 lg:block">
      <div className="mb-4 rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-surface)] p-3">
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">Impact score</p>
        <p className="text-lg font-semibold">{impactScoreLabel(null)}</p>
      </div>
      <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Tools</h2>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No tools yet" onRetry={load}>
        <ul className="space-y-2">
          {tools.map((tool) => (
            <li key={tool.id}>
              <a href={tool.url} target="_blank" rel="noopener noreferrer" className="text-[color:var(--fb-v2-accent)]">
                {tool.name}
              </a>
            </li>
          ))}
        </ul>
      </ScreenBody>
    </aside>
  );
}
