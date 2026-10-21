"use client";

import Link from "next/link";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import { useLayout } from "@/lib/v2/LayoutContext";
import { useOrgData } from "@/lib/v2/useOrgData";

type Task = { id: string; title: string; status: string; due_on: string | null; is_blocked: boolean };
type Me = { seconds_7d: number; impact_score: number | null; by_category?: Record<string, { key: string; seconds: number }> };
const CATEGORY = { projects: "Projects", onboarding: "Onboarding", masterclass: "Masterclasses" } as Record<string, string>;

function Block({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/**
 * The right rail "Your workspace" (spec 10.1): impact score slot, my progress, my tasks (five, with
 * due dates) and buddies, in the order of the saved widgets. Shown beside every page except Home,
 * where the same widgets are the page itself.
 */
export function RightRail({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const { layout } = useLayout();
  const me = useOrgData<Me>(orgId, "/dashboard/me");
  const tasks = useOrgData<{ results: Task[] }>(orgId, "/tasks?mine=1");
  const buddies = useOrgData<{ id: string; name: string; pinned: boolean }[]>(orgId, flag(access, "buddies") ? "/buddies" : null);
  const w = (path: string) => `/w/${orgSlug}${path}`;
  const myTasks = rowsOf<Task>(tasks.data).filter((t) => t.status !== "done").slice(0, 5);
  const hours = ((me.data?.seconds_7d ?? 0) / 3600).toFixed(1);

  const blocks: Record<string, React.ReactNode> = {
    impact: (
      <Block title={tr("Impact score")}>
        <p className="text-sm">{me.data?.impact_score ?? tr("Not configured")}</p>
      </Block>
    ),
    progress: (
      <Block title={tr("My progress")}>
        <p className="text-2xl font-semibold tabular-nums">{tr("{n} h", { n: hours })}</p>
        <p className="mb-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Logged in the last 7 days")}</p>
        <ul className="space-y-0.5 text-sm">
          {Object.values(me.data?.by_category ?? {}).map((c) => (
            <li key={c.key} className="flex justify-between">
              <span>{tr(CATEGORY[c.key] ?? c.key)}</span>
              <span className="tabular-nums">{(c.seconds / 3600).toFixed(1)}</span>
            </li>
          ))}
        </ul>
      </Block>
    ),
    tasks: (
      <Block title={tr("My tasks")} action={<Link className="text-xs hover:underline" href={w("/tasks")}>{tr("All")}</Link>}>
        {myTasks.length === 0 ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No open tasks.")}</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {myTasks.map((t) => (
              <li key={t.id}>
                <p className="truncate">{t.title}</p>
                <p className="flex gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
                  {t.due_on ? <span>{tr("Due {date}", { date: t.due_on })}</span> : null}
                  {t.is_blocked ? <Badge tone="bad">{tr("Blocked")}</Badge> : null}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Block>
    ),
    buddies: flag(access, "buddies") ? (
      <Block title={tr("Buddies")}>
        <p className="mb-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Tap a buddy to route the chat.")}</p>
        <ul className="flex flex-wrap gap-1.5">
          {rowsOf<{ id: string; name: string; pinned: boolean }>(buddies.data)
            .sort((a, b) => Number(b.pinned) - Number(a.pinned))
            .slice(0, 6)
            .map((b) => (
              <li key={b.id}>
                <Link href={w(`/buddies/${b.id}`)} className="inline-block rounded-full px-2.5 py-0.5 text-xs ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:ring-[color:var(--fb-v2-accent)]">
                  {b.name}
                </Link>
              </li>
            ))}
        </ul>
      </Block>
    ) : null,
  };

  const order = layout.widgets.filter((k) => k in blocks);
  return (
    <aside aria-label={tr("Your workspace")} className="hidden w-72 shrink-0 overflow-y-auto border-s border-[color:var(--fb-v2-border)] p-4 xl:block">
      <h2 className="mb-4 text-sm font-semibold">{tr("Your workspace")}</h2>
      {(order.length ? order : ["impact", "progress", "tasks", "buddies"]).map((k) => (blocks[k] ? <div key={k}>{blocks[k]}</div> : null))}
    </aside>
  );
}
