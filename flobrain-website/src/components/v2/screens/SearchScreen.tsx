"use client";

import { useCallback, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import { filterHits, searchEmpty, type SearchHit } from "@/lib/v2/screens/search";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function SearchScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [query, setQuery] = useState("");
  const [type, setType] = useState<"all" | "room" | "task" | "doc" | "meeting">("all");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [state, setState] = useState<ScreenState>(orgState);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(() => {
    if (!orgId || !query.trim()) {
      setResults([]);
      setState("empty");
      return;
    }
    setState("loading");
    v2Client()
      .search(orgId, query.trim())
      .then((payload) => {
        const rows = (payload.results ?? []) as SearchHit[];
        setResults(rows);
        setState(searchEmpty(query, rows) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not search");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, query]);

  const visible = filterHits(results, type);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Search</h1>
      <form
        className="mb-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          run();
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-3 py-2"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search rooms, tasks, docs, meetings"
        />
        <Button type="submit">Search</Button>
      </form>
      <div className="mb-4 flex gap-2 text-sm">
        {(["all", "room", "task", "doc", "meeting"] as const).map((id) => (
          <button key={id} type="button" onClick={() => setType(id)} className={type === id ? "font-semibold" : ""}>
            {id}
          </button>
        ))}
      </div>
      <ScreenBody
        state={orgState !== "ready" ? orgState : state}
        error={error || orgError}
        emptyLabel="No results"
        onRetry={run}
      >
        <ul className="space-y-2">
          {visible.map((row) => (
            <li key={`${row.type}-${row.id}`}>
              <span className="text-[color:var(--fb-v2-text-muted)]">{row.type}</span> · {row.title}
            </li>
          ))}
        </ul>
      </ScreenBody>
    </section>
  );
}
