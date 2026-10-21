"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorState, Loading } from "@/components/v2/states";
import { Badge, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { argsLine, callQuery, duration, EMPTY_FILTERS } from "./logic";
import type { CallFilters, CallLogPage } from "./types";

function Select({ label, value, onChange, children }: { label: string; value: string; onChange: (v: string) => void; children: React.ReactNode }) {
  return (
    <label className="flex min-w-36 flex-1 flex-col text-xs sm:flex-none">
      <span className="mb-1 font-medium text-[color:var(--fb-v2-text-muted)]">{label}</span>
      <select className="v2-input text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
    </label>
  );
}

/** Every MCP call in and out, newest first. Arguments are never stored, only their shape. */
export function CallLog({ orgId }: { orgId: string }) {
  const tr = useTr();
  const [filters, setFilters] = useState<CallFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState<CallLogPage | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .get<CallLogPage>(`/orgs/${orgId}/mcp/calls`, callQuery(filters))
      .then((value) => {
        setPage(value);
        setError("");
      })
      .catch((err) => setError(errorText(err)));
  }, [orgId, filters]);

  useEffect(load, [load]);
  const set = (patch: Partial<CallFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <div className="flex flex-col gap-3">
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => e.preventDefault()} aria-label={tr("Filter calls")}>
        <Select label={tr("Direction")} value={filters.direction} onChange={(v) => set({ direction: v as CallFilters["direction"] })}>
          <option value="">{tr("In and out")}</option>
          <option value="inbound">{tr("Apps calling FloBrain")}</option>
          <option value="outbound">{tr("Buddies calling outside servers")}</option>
        </Select>
        <Select label={tr("Result")} value={filters.ok} onChange={(v) => set({ ok: v as CallFilters["ok"] })}>
          <option value="">{tr("All results")}</option>
          <option value="true">{tr("Worked")}</option>
          <option value="false">{tr("Failed")}</option>
        </Select>
        <Select label={tr("Tool")} value={filters.tool} onChange={(v) => set({ tool: v })}>
          <option value="">{tr("All tools")}</option>
          {(page?.tools ?? []).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
        <Select label={tr("App or server")} value={filters.client} onChange={(v) => set({ client: v })}>
          <option value="">{tr("All")}</option>
          {(page?.clients ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Select label={tr("Period")} value={filters.days} onChange={(v) => set({ days: v })}>
          <option value="1">{tr("Last 24 hours")}</option>
          <option value="7">{tr("Last 7 days")}</option>
          <option value="30">{tr("Last 30 days")}</option>
          <option value="90">{tr("Last 90 days")}</option>
        </Select>
      </form>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : page === null ? (
        <Loading />
      ) : (
        <>
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]" aria-live="polite">
            {tr("{n} calls, {errors} failed. Kept for {days} days.", { n: page.total, errors: page.errors, days: page.retention_days })}
            {page.total > page.results.length ? ` ${tr("Showing the newest {n}.", { n: page.results.length })}` : ""}
          </p>
          {page.results.length === 0 ? (
            <p className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No calls match these filters.")}</p>
          ) : (
            <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
              {page.results.map((r) => (
                <li key={r.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span dir="ltr" className="font-mono font-medium">
                      {r.tool}
                    </span>
                    {r.ok ? <Badge tone="good">{tr("Worked")}</Badge> : <Badge tone="bad">{tr("Failed")}</Badge>}
                    {r.error ? (
                      <span dir="ltr" className="font-mono text-xs text-[color:var(--fb-v2-error)]">
                        {r.error}
                      </span>
                    ) : null}
                    <span className="ms-auto font-mono text-xs text-[color:var(--fb-v2-text-muted)]">{duration(r.duration_ms)}</span>
                  </div>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {r.direction === "inbound" ? tr("{app} called FloBrain", { app: r.client || tr("An app") }) : tr("A buddy called {server}", { server: r.server?.name ?? r.client })}
                    {r.user ? ` · ${tr("for {name}", { name: r.user.name })}` : ""} · {when(r.created_at)}
                  </p>
                  {Object.keys(r.arguments ?? {}).length ? (
                    <p className="text-xs text-[color:var(--fb-v2-text-faint)]">
                      {tr("Arguments (values hidden):")}{" "}
                      <span dir="ltr" className="font-mono">
                        {argsLine(r.arguments)}
                      </span>
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
