"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import { canCreateTool, toolsEmpty, type ToolRow } from "@/lib/v2/screens/tools";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function ToolsScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [tools, setTools] = useState<ToolRow[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
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
    <section>
      <h1 className="mb-4 text-2xl font-semibold">External tools</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No tools yet" onRetry={load}>
        <ul className="mb-6 space-y-2">
          {tools.map((tool) => (
            <li key={tool.id} className="flex items-center justify-between gap-2">
              <a href={tool.url} target="_blank" rel="noopener noreferrer">
                {tool.name}
              </a>
              <Button type="button" variant="ghost" onClick={() => orgId && v2Client().deleteTool(orgId, tool.id).then(load)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      </ScreenBody>
      <form
        className="mt-4 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!orgId || !canCreateTool(name, url)) return;
          v2Client()
            .createTool(orgId, name, url)
            .then(() => {
              setName("");
              setUrl("");
              load();
            })
            .catch((err: { response?: { status?: number } }) => {
              setError("Could not add tool");
              setState(screenStateFromHttp(err.response?.status ?? 500));
            });
        }}
      >
        <input
          className="rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-3 py-2"
          placeholder="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <input
          className="min-w-56 flex-1 rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-3 py-2"
          placeholder="https://"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <Button type="submit">Add</Button>
      </form>
    </section>
  );
}
