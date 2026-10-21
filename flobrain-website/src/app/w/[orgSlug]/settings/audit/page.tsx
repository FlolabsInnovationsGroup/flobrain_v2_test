"use client";

import { useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, PageHeader, Row, Rows } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import { auditQuery, displayName, pageCount, type Member } from "@/lib/v2/screens/people";
import { useOrgData } from "@/lib/v2/useOrgData";
import { NoAccess } from "@/components/v2/states";

type Event = {
  id: string;
  action: string;
  actor_user: { id: string; username: string } | null;
  impersonator_user: { id: string; username: string } | null;
  target_type: string;
  target_id: string;
  payload: Record<string, unknown>;
  ip: string | null;
  created_at: string;
};

/** Read-only audit log (R4). Nobody can edit it; ``audit.view`` reads it. */
export default function AuditPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const allowed = has(access, "audit.view");
  const [filters, setFilters] = useState({ actor: "", action: "", since: "", until: "", page: 1 });
  const query = useMemo(() => new URLSearchParams(auditQuery(filters)).toString(), [filters]);
  const events = useOrgData<{ count: number; results: Event[] }>(orgId, allowed ? `/audit-events?${query}` : null, { list: true });
  const actions = useOrgData<string[]>(orgId, allowed ? "/audit-events/actions" : null);
  const people = useOrgData<{ results: Member[] }>(orgId, allowed ? "/members?page_size=100" : null);
  const set = (next: Partial<typeof filters>) => setFilters((f) => ({ ...f, ...next, page: next.page ?? 1 }));
  const pages = pageCount(events.data?.count ?? 0);

  if (access && !allowed) return <NoAccess />;

  return (
    <div className="max-w-5xl">
      <PageHeader title={tr("Audit log")} intro={tr("Every status change, grant, key change and admin action, newest first. Nobody can edit or delete these rows.")} />
      <div className="mb-4 flex flex-wrap items-end gap-3 text-sm">
        <label>
          <span className="mb-1 block font-medium">{tr("Who")}</span>
          <select className="v2-input w-48" value={filters.actor} onChange={(e) => set({ actor: e.target.value })}>
            <option value="">{tr("Anyone")}</option>
            {rowsOf<Member>(people.data).map((m) => (
              <option key={m.id} value={m.id}>
                {displayName(m)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block font-medium">{tr("Action")}</span>
          <input className="v2-input w-48" list="audit-actions" value={filters.action} onChange={(e) => set({ action: e.target.value })} placeholder={tr("For example perm or member.status")} />
          <datalist id="audit-actions">
            {(actions.data ?? []).map((a) => (
              <option key={a} value={a} />
            ))}
          </datalist>
        </label>
        <label>
          <span className="mb-1 block font-medium">{tr("From")}</span>
          <input className="v2-input" type="date" value={filters.since} onChange={(e) => set({ since: e.target.value })} />
        </label>
        <label>
          <span className="mb-1 block font-medium">{tr("To")}</span>
          <input className="v2-input" type="date" value={filters.until} onChange={(e) => set({ until: e.target.value })} />
        </label>
        <Button variant="ghost" onClick={() => setFilters({ actor: "", action: "", since: "", until: "", page: 1 })}>
          {tr("Clear filters")}
        </Button>
      </div>
      <ScreenBody state={events.state} error={events.error} emptyLabel={tr("Nothing matches these filters.")} onRetry={events.reload}>
        <Rows>
          {(events.data?.results ?? []).map((e) => (
            <Row key={e.id} className="items-start">
              <div className="min-w-0">
                <p className="font-medium">
                  <code className="text-sm">{e.action}</code>
                  {e.target_type ? <span className="text-[color:var(--fb-v2-text-muted)]"> · {e.target_type}</span> : null}
                </p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {e.actor_user ? e.actor_user.username : tr("System")}
                  {e.impersonator_user ? ` · ${tr("support session by {name}", { name: e.impersonator_user.username })}` : ""}
                  {e.ip ? ` · ${e.ip}` : ""}
                </p>
                {Object.keys(e.payload ?? {}).length ? (
                  <details className="mt-1 text-xs">
                    <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Details")}</summary>
                    <pre className="mt-1 max-w-full overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify(e.payload, null, 2)}</pre>
                  </details>
                ) : null}
              </div>
              <span className="flex shrink-0 items-center gap-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                {e.impersonator_user ? <Badge tone="waiting">{tr("Support")}</Badge> : null}
                <time dateTime={e.created_at}>{new Date(e.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time>
              </span>
            </Row>
          ))}
        </Rows>
        {pages > 1 ? (
          <nav aria-label={tr("Pages")} className="mt-4 flex items-center gap-3 text-sm">
            <Button variant="outline" disabled={filters.page <= 1} onClick={() => set({ page: filters.page - 1 })}>
              {tr("Previous")}
            </Button>
            <span>{tr("Page {page} of {pages}", { page: filters.page, pages })}</span>
            <Button variant="outline" disabled={filters.page >= pages} onClick={() => set({ page: filters.page + 1 })}>
              {tr("Next")}
            </Button>
          </nav>
        ) : null}
      </ScreenBody>
    </div>
  );
}
