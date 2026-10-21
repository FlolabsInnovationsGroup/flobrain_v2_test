"use client";

import { useState } from "react";

import { AddMemory } from "@/components/v2/memory/AddMemory";
import { Explainer } from "@/components/v2/memory/Explainer";
import { MemoryRow, type RowChange } from "@/components/v2/memory/MemoryRow";
import { PendingList } from "@/components/v2/memory/PendingList";
import { RulesForm } from "@/components/v2/memory/RulesForm";
import { TeamMemory } from "@/components/v2/memory/TeamMemory";
import { CATEGORIES, categoryLabel, filterItems, splitByStatus, type Category, type MemoryItem, type Rules, type Summary, type TeamRow } from "@/components/v2/memory/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tab = "me" | "team" | "rules";

export default function MemoryPage() {
  const { orgId } = useAccess();
  const tr = useTr();
  const summary = useOrgData<Summary>(orgId, "/memory");
  const mine = useOrgData<MemoryItem[]>(orgId, "/memory/items?status=all");
  const teamItems = useOrgData<MemoryItem[]>(orgId, "/memory/items?scope=team&status=active");
  const manager = !!summary.data?.can_manage;
  const rules = useOrgData<Rules>(orgId, manager ? "/memory/rules" : null);
  const teams = useOrgData<TeamRow[]>(orgId, manager ? "/memory/teams" : null);

  const [tab, setTab] = useState<Tab>("me");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const { active, pending } = splitByStatus(rowsOf<MemoryItem>(mine.data));
  const shown = filterItems(active, query, category);
  const data = summary.data;
  const blocked = data?.rules.blocked_categories ?? [];
  const base = `/orgs/${orgId}/memory`;

  function reload() {
    summary.reload();
    mine.reload();
    teamItems.reload();
    if (manager) {
      rules.reload();
      teams.reload();
    }
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      reload();
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
      return false;
    }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "me", label: tr("About you") },
    { key: "team", label: tr("Team memory") },
    ...(manager ? [{ key: "rules" as Tab, label: tr("Rules") }] : []),
  ];

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("What buddies remember")}
        intro={tr("Short notes buddies keep so you don't repeat yourself. You can see, change and delete all of them.")}
        action={
          data ? (
            <Button
              variant="outline"
              aria-pressed={data.me.paused}
              onClick={() =>
                act(() => api.put(`${base}/me`, { paused: !data.me.paused }), data.me.paused ? tr("Memory is on again.") : tr("Memory is paused for you."))
              }
            >
              {data.me.paused ? tr("Resume memory") : tr("Pause memory for me")}
            </Button>
          ) : null
        }
      />

      <ScreenBody state={summary.state} error={summary.error} onRetry={reload}>
        {data ? (
          <>
            {!data.rules.enabled ? <Notice>{tr("Your organization has turned buddy memory off. Buddies don't save or use anything. You can still delete what is here.")}</Notice> : null}
            {data.me.paused ? <Notice>{tr("Memory is paused for you. Buddies don't save or use anything about you until you resume.")}</Notice> : null}
            {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

            <div role="tablist" aria-label={tr("Memory sections")} className="mb-6 flex gap-1 overflow-x-auto border-b border-[color:var(--fb-v2-border)]">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  id={`memory-tab-${t.key}`}
                  role="tab"
                  aria-selected={tab === t.key}
                  aria-controls={`memory-panel-${t.key}`}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm ${tab === t.key ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]"}`}
                >
                  {t.label}
                  {t.key === "me" && pending.length ? <span className="ms-1 text-[color:var(--fb-v2-waiting)]">({pending.length})</span> : null}
                </button>
              ))}
            </div>

            {tab === "me" ? (
              <div role="tabpanel" id="memory-panel-me" aria-labelledby="memory-tab-me">
                <Explainer rules={data.rules} never={data.never_stored} />
                <PendingList
                  items={pending}
                  onKeep={(item) => act(() => api.post(`${base}/items/${item.id}/confirm`), tr("Saved."))}
                  onDrop={(item) => act(() => api.post(`${base}/items/${item.id}/reject`), tr("Dropped. Buddies won't suggest it again."))}
                />
                <Section title={tr("Add a note about yourself")}>
                  {data.rules.enabled ? (
                    <AddMemory
                      id="memory-add"
                      label={tr("What should buddies know about you?")}
                      placeholder={tr("For example: I prefer short answers with bullet points")}
                      blocked={blocked}
                      onAdd={(text, cat) => act(() => api.post(`${base}/items`, { text, category: cat }), tr("Saved."))}
                    />
                  ) : null}
                </Section>
                <Section
                  title={tr("Your memories ({n})", { n: active.length })}
                  aside={
                    active.length || pending.length ? (
                      <Button
                        variant="danger"
                        onClick={() => {
                          if (window.confirm(tr("Delete everything buddies remember about you in this organization? This can't be undone.")))
                            act(() => api.del(`${base}/items`), tr("Deleted. Buddies remember nothing about you here."));
                        }}
                      >
                        {tr("Delete all")}
                      </Button>
                    ) : null
                  }
                >
                  <div className="mb-3 flex flex-wrap gap-2">
                    <label className="min-w-0 flex-1 basis-56 text-sm">
                      <span className="sr-only">{tr("Search your memories")}</span>
                      <input className="v2-input" type="search" dir="auto" placeholder={tr("Search your memories")} value={query} onChange={(e) => setQuery(e.target.value)} />
                    </label>
                    <label className="text-sm">
                      <span className="sr-only">{tr("Category")}</span>
                      <select className="v2-input w-auto" value={category} onChange={(e) => setCategory(e.target.value as Category | "")}>
                        <option value="">{tr("All categories")}</option>
                        {CATEGORIES.map((c) => (
                          <option key={c} value={c}>
                            {categoryLabel(tr, c)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {shown.length ? (
                    <Rows>
                      {shown.map((item) => (
                        <MemoryRow
                          key={`${item.id}-${item.updated_at}`}
                          item={item}
                          editable
                          blocked={blocked}
                          onSave={(change: RowChange) => act(() => api.patch(`${base}/items/${item.id}`, change), tr("Saved."))}
                          onDelete={() => {
                            if (window.confirm(tr("Delete this memory?"))) act(() => api.del(`${base}/items/${item.id}`), tr("Deleted."));
                          }}
                        />
                      ))}
                    </Rows>
                  ) : (
                    <Notice>{active.length ? tr("Nothing matches your search.") : tr("Buddies don't remember anything about you yet.")}</Notice>
                  )}
                </Section>
              </div>
            ) : null}

            {tab === "team" ? (
              <div role="tabpanel" id="memory-panel-team" aria-labelledby="memory-tab-team">
                {!data.rules.team_memory ? <Notice>{tr("Team memory is off in your organization.")}</Notice> : null}
                {manager && orgId ? (
                  <Section title={tr("Manage team notes")}>
                    <TeamMemory
                      key={teams.data ? "ready" : "loading"}
                      orgId={orgId}
                      teams={rowsOf<TeamRow>(teams.data)}
                      enabled={data.rules.enabled && data.rules.team_memory}
                      blocked={blocked}
                      onChanged={() => {
                        teams.reload();
                        teamItems.reload();
                      }}
                    />
                  </Section>
                ) : null}
                <Section title={tr("Notes about your teams")}>
                  <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                    {tr("Buddies use these for everyone in the team. People who manage memory can change them.")}
                  </p>
                  {rowsOf<MemoryItem>(teamItems.data).length ? (
                    <Rows>
                      {rowsOf<MemoryItem>(teamItems.data).map((item) => (
                        <MemoryRow key={item.id} item={item} editable={false} />
                      ))}
                    </Rows>
                  ) : (
                    <Notice>{data.teams.length ? tr("No notes for your teams yet.") : tr("You are not in a team yet.")}</Notice>
                  )}
                </Section>
              </div>
            ) : null}

            {tab === "rules" && manager ? (
              <div role="tabpanel" id="memory-panel-rules" aria-labelledby="memory-tab-rules">
                <Section title={tr("Memory rules for your organization")}>
                  {rules.data ? (
                    <>
                      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                        {tr("{p} personal and {t} team notes are kept right now. You can't read personal notes; only their owner can.", {
                          p: rules.data.totals?.personal ?? 0,
                          t: rules.data.totals?.team ?? 0,
                        })}
                      </p>
                      <RulesForm
                        key={rules.data.updated_at ?? "default"}
                        rules={{ ...rules.data, totals: undefined }}
                        onSave={(next) => act(() => api.put(`${base}/rules`, next), tr("Rules saved."))}
                      />
                    </>
                  ) : (
                    <ScreenBody state={rules.state} error={rules.error} onRetry={rules.reload}>
                      {null}
                    </ScreenBody>
                  )}
                </Section>
              </div>
            ) : null}
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
