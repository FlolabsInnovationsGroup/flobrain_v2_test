"use client";

import { useState } from "react";

import { BudgetMeter, type BudgetRow } from "@/components/v2/ai/BudgetMeter";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { apiClient } from "@/lib/axios";
import { cn } from "@/lib/utils";

type Bucket = {
  key: string;
  label: string;
  calls: number;
  errors: number;
  total_tokens: number;
  platform_tokens: number;
  platform_cost: string;
  unpriced_calls: number;
  own_key_calls: number;
  own_key_tokens: number;
};
type Summary = { days: number; group: string; scope: "org" | "teams" | "own"; totals: Bucket; results: Bucket[] };

const GROUPS = [
  ["member", "By member"],
  ["team", "By team"],
  ["model", "By model"],
  ["surface", "By feature"],
] as const;
const SURFACES: Record<string, string> = {
  room_ai: "Room AI",
  buddy: "Buddies",
  scheduled_agent: "Scheduled agents",
  knowledge_ask: "Ask the org",
  translation: "Translation",
  content_studio: "Content Studio",
  meeting: "Meetings",
  learning: "Learning",
  evaluation: "Evaluations",
  mcp: "MCP",
  public_api: "Public API",
  render: "GPU renders",
  other: "Other",
};
const HEAD: Record<string, string> = { member: "Member", team: "Team", model: "Model", surface: "Feature" };
const SCOPE: Record<string, string> = {
  org: "Showing everyone in the organization.",
  teams: "Showing you and the members of the teams you lead.",
  own: "Showing your own use.",
};

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{note}</p> : null}
    </div>
  );
}

export function UsageScreen() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const [group, setGroup] = useState<(typeof GROUPS)[number][0]>("member");
  const [days, setDays] = useState(30);
  const summary = useOrgData<Summary>(orgId, `/usage/summary?group=${group}&days=${days}`);
  const mine = useOrgData<BudgetRow[]>(orgId, flag(access, "budgets") ? "/budgets/mine" : null, { list: true });
  const [message, setMessage] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const s = summary.data;
  const n = (v: number) => v.toLocaleString();

  function name(b: Bucket) {
    if (group === "surface") return SURFACES[b.key] ? tr(SURFACES[b.key]) : b.key;
    if (!b.label) return group === "team" ? tr("No team") : group === "member" ? tr("Former member") : tr("Unknown model");
    if (b.key === "team_members") return tr("Your team members (combined)");
    if (b.key === "private") return tr("People who keep their insights personal");
    return b.label;
  }

  async function exportCsv() {
    setMessage(null);
    setExporting(true);
    try {
      const res = await apiClient.get<Blob>(`/api/v2/orgs/${orgId}/usage/export`, { params: { days: String(days) }, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `ai-usage-${days}d.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMessage(errorText(err));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("AI usage")}
        intro={tr("Tokens and cost from real usage records. Platform models are billed at cost; your own keys are billed by your provider, with no FloBrain markup.")}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <select className="v2-input w-40" aria-label={tr("Period")} value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={1}>{tr("Today")}</option>
              <option value={7}>{tr("Last 7 days")}</option>
              <option value={30}>{tr("Last 30 days")}</option>
              <option value={90}>{tr("Last 90 days")}</option>
            </select>
            <Button variant={exporting ? "waiting" : "outline"} disabled={exporting} onClick={exportCsv}>
              {exporting ? tr("Preparing…") : tr("Export CSV")}
            </Button>
          </div>
        }
      />
      {message ? <Notice kind="error">{message}</Notice> : null}
      {rowsOf<BudgetRow>(mine.data).length ? (
        <Section title={tr("Budgets that apply to you")}>
          <div className="grid gap-3 sm:grid-cols-2">
            {rowsOf<BudgetRow>(mine.data).map((b) => (
              <BudgetMeter key={b.id} budget={b} />
            ))}
          </div>
        </Section>
      ) : null}
      <div role="tablist" className="mb-4 flex flex-wrap gap-1 border-b border-[color:var(--fb-v2-border)]">
        {GROUPS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={group === key}
            onClick={() => setGroup(key)}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm", group === key ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]")}
          >
            {tr(label)}
          </button>
        ))}
      </div>
      <ScreenBody state={summary.state} error={summary.error} onRetry={summary.reload}>
        {s ? (
          <>
            <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">{tr(SCOPE[s.scope] ?? SCOPE.own)}</p>
            <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Tile label={tr("Platform cost")} value={`$${s.totals.platform_cost}`} note={s.totals.unpriced_calls ? tr("{n} calls have no price yet", { n: s.totals.unpriced_calls }) : tr("At cost, from the price table")} />
              <Tile label={tr("Platform tokens")} value={n(s.totals.platform_tokens)} note={tr("{n} calls", { n: n(s.totals.calls - s.totals.own_key_calls) })} />
              <Tile label={tr("Tokens on own keys")} value={n(s.totals.own_key_tokens)} note={tr("{n} calls, billed by your provider", { n: n(s.totals.own_key_calls) })} />
              <Tile label={tr("Failed calls")} value={n(s.totals.errors)} />
            </div>
            {s.results.length === 0 ? (
              <Notice>{tr("No AI use in this period.")}</Notice>
            ) : (
              <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
                <table className="w-full text-sm">
                  <thead className="text-[color:var(--fb-v2-text-muted)]">
                    <tr>
                      {[HEAD[group], "Calls", "Platform tokens", "Platform cost", "Own-key tokens"].map((h) => (
                        <th key={h} className="px-4 py-2 text-start font-medium">
                          {tr(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {s.results.map((b) => (
                      <tr key={b.key || "none"} className="border-t border-[color:var(--fb-v2-border)]">
                        <td className="px-4 py-2">{name(b)}</td>
                        <td className="px-4 py-2 tabular-nums">
                          {n(b.calls)}
                          {b.errors ? <span className="text-[color:var(--fb-v2-text-muted)]"> {tr("({n} failed)", { n: b.errors })}</span> : null}
                        </td>
                        <td className="px-4 py-2 tabular-nums">{n(b.platform_tokens)}</td>
                        <td className="px-4 py-2 tabular-nums">
                          ${b.platform_cost}
                          {b.unpriced_calls ? <span className="text-[color:var(--fb-v2-text-muted)]"> {tr("({n} unpriced)", { n: b.unpriced_calls })}</span> : null}
                        </td>
                        <td className="px-4 py-2 tabular-nums">{n(b.own_key_tokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
