"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AddSource } from "@/components/v2/data/AddSource";
import { CardTile } from "@/components/v2/data/CardTile";
import { ReportsPanel } from "@/components/v2/data/ReportsPanel";
import type { Card, Dataset, Meta, Report } from "@/components/v2/data/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tab = "sources" | "cards" | "reports";
const TABS: Tab[] = ["sources", "cards", "reports"];

export default function DataPage() {
  return (
    <Suspense>
      <DataScreen />
    </Suspense>
  );
}

function StatusBadge({ d }: { d: Dataset }) {
  const tr = useTr();
  if (d.status === "error") return <Badge tone="bad">{tr("Needs attention")}</Badge>;
  if (d.status === "refreshing") return <Badge>{tr("Refreshing")}</Badge>;
  return <Badge tone="good">{tr("Ready")}</Badge>;
}

function DataScreen() {
  const tr = useTr();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { orgId, access } = useAccess();
  const tab: Tab = TABS.includes(params.get("tab") as Tab) ? (params.get("tab") as Tab) : "sources";
  const datasets = useOrgData<Dataset[]>(orgId, "/data/datasets");
  const { data: meta, reload: reloadMeta } = useOrgData<Meta>(orgId, "/data/meta");
  const cards = useOrgData<Card[]>(orgId, tab === "sources" ? null : "/data/cards");
  const reports = useOrgData<Report[]>(orgId, tab === "reports" ? "/data/reports" : null);
  const { data: teams } = useOrgData<{ id: string; name: string }[]>(orgId, meta?.can_manage ? "/teams" : null);
  const { data: rooms } = useOrgData<{ id: string; name: string; kind: string }[]>(orgId, tab === "reports" ? "/rooms" : null);
  const { data: members } = useOrgData<unknown>(orgId, tab === "reports" ? "/members" : null);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const rows = rowsOf<Dataset>(datasets.data);
  const canManage = has(access, "data.manage");

  const go = (next: Tab) => router.replace(`/w/${orgSlug}/data${next === "sources" ? "" : `?tab=${next}`}`);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      datasets.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const kindLabel = (d: Dataset) => tr({ upload: "Uploaded file", sheet: "Google Sheet", postgres: "PostgreSQL" }[d.kind]);
  const sharedLabel = (d: Dataset) => tr({ org: "Everyone", team: "A team", owner: "Only me" }[d.visibility]);

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Data")}
        intro={tr("Ask questions about your spreadsheets and databases in plain language. Every answer shows the chart and the SQL it used.")}
        action={
          canManage && tab === "sources" ? (
            <Button onClick={() => setAdding((v) => !v)} aria-expanded={adding}>
              {adding ? tr("Close") : tr("Add a source")}
            </Button>
          ) : null
        }
      />
      <div role="tablist" aria-label={tr("Data sections")} className="mb-6 flex gap-1 border-b border-[color:var(--fb-v2-border)]">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => go(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]"}`}
          >
            {tr({ sources: "Sources", cards: "Saved cards", reports: "Reports" }[t])}
          </button>
        ))}
      </div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      {tab === "sources" ? (
        <>
          {adding && orgId ? (
            <div className="mb-6">
              <AddSource
                orgId={orgId}
                meta={meta}
                teams={rowsOf<{ id: string; name: string }>(teams)}
                onAdded={(d) => {
                  setAdding(false);
                  router.push(`/w/${orgSlug}/data/${d.id}`);
                }}
              />
            </div>
          ) : null}
          <ScreenBody state={datasets.state === "ready" && !rows.length ? "empty" : datasets.state} error={datasets.error} emptyLabel={tr(canManage ? "No data yet. Add a file, a Google Sheet or a database." : "No data shared with you yet.")} onRetry={datasets.reload}>
            <Rows>
              {rows.map((d) => (
                <Row key={d.id}>
                  <div className="min-w-0 flex-1 basis-64">
                    <Link href={`/w/${orgSlug}/data/${d.id}`} className="font-medium underline-offset-2 hover:underline">
                      {d.name}
                    </Link>
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {kindLabel(d)} · {d.kind === "postgres" ? tr("{n} tables", { n: d.tables.length }) : tr("{n} rows", { n: d.row_count.toLocaleString() })} · {sharedLabel(d)}
                      {d.last_refreshed_at ? ` · ${tr("Updated {when}", { when: when(d.last_refreshed_at) })}` : ""}
                    </p>
                    {d.status === "error" && d.last_error ? <p className="text-xs text-[color:var(--fb-v2-error)]">{d.last_error}</p> : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge d={d} />
                    {d.can_manage && d.kind !== "upload" ? (
                      <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/data/datasets/${d.id}/refresh`), tr("Refreshed."))}>
                        {tr("Refresh")}
                      </Button>
                    ) : null}
                    <Button asChild variant="ghost">
                      <Link href={`/w/${orgSlug}/data/${d.id}`}>{tr("Ask")}</Link>
                    </Button>
                  </div>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
          {meta?.is_admin && canManage ? (
            <Section title={tr("Data settings")}>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={meta.allow_private_hosts}
                  onChange={(e) =>
                    act(async () => {
                      await api.patch(`/orgs/${orgId}/data/settings`, { allow_private_hosts: e.target.checked });
                      reloadMeta();
                    }, tr("Saved."))
                  }
                />
                <span>
                  <span className="block font-medium">{tr("Allow databases on a private network")}</span>
                  <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Only turn this on for self-hosted installs where the database is inside your own network.")}</span>
                </span>
              </label>
            </Section>
          ) : null}
        </>
      ) : null}

      {tab === "cards" && orgId ? (
        <ScreenBody state={cards.state === "ready" && !rowsOf(cards.data).length ? "empty" : cards.state} error={cards.error} emptyLabel={tr("No saved cards yet. Ask a question and save the answer.")} onRetry={cards.reload}>
          <ul className="grid gap-4 lg:grid-cols-2">
            {rowsOf<Card>(cards.data).map((c) => (
              <CardTile key={c.id} orgId={orgId} card={c} canDelete={c.created_by === access?.user_id || !!meta?.is_admin} onChange={cards.reload} />
            ))}
          </ul>
        </ScreenBody>
      ) : null}

      {tab === "reports" && orgId ? (
        <ScreenBody state={reports.state === "empty" ? "ready" : reports.state} error={reports.error} onRetry={reports.reload}>
          <ReportsPanel
            orgId={orgId}
            reports={rowsOf<Report>(reports.data)}
            cards={rowsOf<Card>(cards.data)}
            rooms={rowsOf<{ id: string; name: string; kind: string }>(rooms).filter((r) => r.kind !== "direct")}
            members={rowsOf<{ id: string; username: string }>(members).map((m) => ({ id: m.id, name: m.username }))}
            userId={access?.user_id ?? null}
            isAdmin={!!meta?.is_admin}
            focus={params.get("report")}
            onChange={reports.reload}
          />
        </ScreenBody>
      ) : null}
    </div>
  );
}
