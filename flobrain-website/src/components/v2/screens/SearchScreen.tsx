"use client";

import { useCallback, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { v2Client } from "@/lib/v2/client";
import { filterHits, searchEmpty, type SearchHit } from "@/lib/v2/screens/search";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

/** English display labels for result types; translated at render. */
const TYPE_LABELS: Record<string, string> = { all: "All", room: "Room", task: "Task", doc: "Doc", meeting: "Meeting" };

export function SearchScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const tr = useTr();
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
        setError(tr("Could not search"));
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, query, tr]);

  const visible = filterHits(results, type);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{tr("Search")}</h1>
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
          placeholder={tr("Search rooms, tasks, docs, meetings")}
        />
        <Button type="submit">{tr("Search")}</Button>
      </form>
      <div className="mb-4 flex gap-2 text-sm">
        {(["all", "room", "task", "doc", "meeting"] as const).map((id) => (
          <button key={id} type="button" onClick={() => setType(id)} className={type === id ? "font-semibold" : ""}>
            {tr(TYPE_LABELS[id])}
          </button>
        ))}
      </div>
      <ScreenBody
        state={orgState !== "ready" ? orgState : state}
        error={error || orgError}
        emptyLabel={tr("No results")}
        onRetry={run}
      >
        <ul className="space-y-2">
          {visible.map((row) => (
            <li key={`${row.type}-${row.id}`}>
              <span className="text-[color:var(--fb-v2-text-muted)]">{TYPE_LABELS[row.type] ? tr(TYPE_LABELS[row.type]) : row.type}</span> · {row.title}
            </li>
          ))}
        </ul>
      </ScreenBody>
    </section>
  );
}
