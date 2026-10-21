"use client";

import { Bot, Clock, FileText, Hash, Layers, Workflow } from "lucide-react";
import { useState } from "react";

import { type PackSummary } from "@/components/v2/growth/growth";
import { KIND_LABEL, PackDialog } from "@/components/v2/growth/PackDialog";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, PageHeader, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

const ICONS = { room: Hash, doc: FileText, buddy: Bot, automation: Workflow, time_tag: Clock } as const;

export default function PacksPage() {
  const { orgId } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<{ results: PackSummary[] }>(orgId, "/packs", { list: true });
  const [dialog, setDialog] = useState<{ pack: PackSummary; mode: "install" | "uninstall" } | null>(null);
  const packs = rowsOf<PackSummary>(data);

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Industry packs")}
        intro={tr("Set up FloBrain for your kind of work in one step: rooms, buddies, starter documents and workflows. You see everything before it is created, and you can remove it later.")}
      />
      <ScreenBody state={state} error={error} emptyLabel={tr("No packs yet.")} onRetry={reload}>
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {packs.map((p) => (
            <li key={p.key} className="flex flex-col gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-[color:var(--fb-v2-accent-soft)]" aria-hidden>
                    <Layers size={18} className="text-[color:var(--fb-v2-accent)]" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="font-semibold">{tr(p.name)}</h2>
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr(p.audience)}</p>
                  </div>
                </div>
                {p.installed ? <Badge tone="good">{tr("Installed")}</Badge> : null}
              </div>
              <p className="text-sm">{tr(p.summary)}</p>
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[color:var(--fb-v2-text-muted)]">
                {(Object.keys(p.counts) as (keyof typeof ICONS)[]).map((kind) => {
                  const Icon = ICONS[kind];
                  return (
                    <li key={kind} className="inline-flex items-center gap-1">
                      <Icon size={12} aria-hidden />
                      {tr(KIND_LABEL[kind])}: {p.counts[kind]}
                    </li>
                  );
                })}
              </ul>
              {p.installed && p.installed_at ? (
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Installed {date}", { date: when(p.installed_at) })}</p>
              ) : null}
              <div className="mt-auto flex flex-wrap gap-2 pt-1">
                <Button variant={p.installed ? "outline" : "default"} onClick={() => setDialog({ pack: p, mode: "install" })}>
                  {p.installed ? tr("Check for missing items") : tr("Preview and install")}
                </Button>
                {p.installed ? (
                  <Button variant="ghost" onClick={() => setDialog({ pack: p, mode: "uninstall" })}>
                    {tr("Uninstall")}
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </ScreenBody>
      {dialog && orgId ? <PackDialog orgId={orgId} pack={dialog.pack} mode={dialog.mode} onClose={() => setDialog(null)} onDone={reload} /> : null}
    </div>
  );
}
