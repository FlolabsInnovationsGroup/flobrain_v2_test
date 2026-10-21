"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { t, useLocale } from "@/i18n";
import { flag } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import { useTr } from "@/i18n/phrases";
import { useLayout, type Layout } from "@/lib/v2/LayoutContext";
import { ROOM_TABS } from "@/lib/v2/layoutRules";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

type Task = { id: string; title: string; status: string; due_on: string | null; is_blocked: boolean };
const WIDGETS: [string, string][] = [
  ["tasks", "home.myTasks"],
  ["approvals", "home.approvals"],
  ["progress", "home.progress"],
  ["impact", "home.impact"],
  ["buddies", "home.buddies"],
  ["announcements", "home.announcements"],
  ["commission", "home.commission"],
];

function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function HomeScreen({ orgSlug }: { orgSlug: string }) {
  const locale = useLocale();
  const { orgId, access } = useAccess();
  const tr = useTr();
  const { cockpit, save, layout, enabled } = useLayout();
  const [draft, setDraft] = useState<Layout | null>(null);
  const [saved, setSaved] = useState(false);
  const me = useOrgData<{ seconds_7d: number; impact_score: number | null }>(orgId, "/dashboard/me");
  const tasks = useOrgData<{ results: Task[] }>(orgId, "/tasks?mine=1");
  const actions = useOrgData<{ status: string }[]>(orgId, flag(access, "ai_actions") ? "/actions" : null);
  const buddies = useOrgData<{ id: string; name: string; pinned: boolean }[]>(orgId, flag(access, "buddies") ? "/buddies" : null);
  const news = useOrgData<{ id: string; body: string }[]>(orgId, "/announcements");
  const commissions = useOrgData<{ earned: string; pending: string }>(orgId, flag(access, "commissions") ? "/commissions/summary" : null);
  const w = (path: string) => `/w/${orgSlug}${path}`;
  const myTasks = rowsOf<Task>(tasks.data).filter((task) => task.status !== "done").slice(0, 5);
  const waiting = rowsOf<{ status: string }>(actions.data).filter((a) => a.status === "proposed").length;
  const hours = ((me.data?.seconds_7d ?? 0) / 3600).toFixed(1);

  const widget: Record<string, React.ReactNode> = {
    tasks: (
      <Card title={t(locale, "home.myTasks")} action={<Link className="text-sm hover:underline" href={w("/tasks")}>{t(locale, "home.all")}</Link>}>
        {myTasks.length === 0 ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{t(locale, "home.noTasks")}</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {myTasks.map((task) => (
              <li key={task.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{task.title}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {task.is_blocked ? <Badge tone="bad">{t(locale, "home.blocked")}</Badge> : null}
                  {task.due_on ? <span className="text-[color:var(--fb-v2-text-muted)]">{task.due_on}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    ),
    approvals: flag(access, "ai_actions") ? (
      <Card title={t(locale, "home.approvals")}>
        <p className="text-3xl font-semibold" style={{ color: waiting ? "var(--fb-v2-waiting)" : undefined }}>
          {waiting}
        </p>
        <Link className="text-sm hover:underline" href={w("/approvals")}>
          {waiting ? t(locale, "home.review") : t(locale, "home.caughtUp")}
        </Link>
      </Card>
    ) : null,
    progress: (
      <Card title={t(locale, "home.progress")}>
        <p className="text-3xl font-semibold">{t(locale, "home.hours").replace("{n}", hours)}</p>
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{t(locale, "home.last7")}</p>
      </Card>
    ),
    impact: (
      <Card title={t(locale, "home.impact")}>
        <p className="text-xl font-semibold">{me.data?.impact_score ?? t(locale, "home.notConfigured")}</p>
      </Card>
    ),
    buddies: flag(access, "buddies") ? (
      <Card title={t(locale, "home.buddies")} action={<Link className="text-sm hover:underline" href={w("/buddies")}>{t(locale, "home.all")}</Link>}>
        <ul className="flex flex-wrap gap-2">
          {rowsOf<{ id: string; name: string; pinned: boolean }>(buddies.data)
            .sort((a, b) => Number(b.pinned) - Number(a.pinned))
            .slice(0, 6)
            .map((b) => (
              <li key={b.id}>
                <Link href={w(`/buddies/${b.id}`)} className="inline-block rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:ring-[color:var(--fb-v2-accent)]">
                  {b.name}
                </Link>
              </li>
            ))}
        </ul>
      </Card>
    ) : null,
    announcements: (
      <Card title={t(locale, "home.announcements")}>
        {rowsOf<{ id: string; body: string }>(news.data).length === 0 ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{t(locale, "home.noAnnouncements")}</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {rowsOf<{ id: string; body: string }>(news.data).map((n) => (
              <li key={n.id}>{n.body}</li>
            ))}
          </ul>
        )}
      </Card>
    ),
    commission: flag(access, "commissions") && commissions.data ? (
      <Card title={t(locale, "home.commission")} action={<Link className="text-sm hover:underline" href={w("/commissions")}>{t(locale, "home.all")}</Link>}>
        <p className="text-2xl font-semibold">{commissions.data.earned}</p>
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
          {t(locale, "home.pending")}: {commissions.data.pending}
        </p>
      </Card>
    ) : null,
  };

  const editing = draft ?? cockpit.layout;
  const ROOM_TAB_LABEL: Record<string, string> = {
    chat: "Chat",
    ai: "room tab|AI",
    tasks: "Tasks",
    docs: "Docs",
    calendar: "Calendar",
    recordings: "Recordings",
    report: "Report",
    team: "Team",
  };

  return (
    <div className={cn("max-w-6xl", layout.panels.compact && "mx-auto max-w-3xl")}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">{t(locale, "home.title")}</h1>
        {enabled ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Switch between Default, Focus and Custom in the top bar.")}</p> : null}
      </div>

      {enabled && cockpit.mode === "custom" ? (
        <details className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4" open={draft !== null} onToggle={(e) => !(e.target as HTMLDetailsElement).open || setDraft(cockpit.layout)}>
          <summary className="cursor-pointer text-sm font-medium">{t(locale, "home.customize")}</summary>
          <fieldset className="mt-3 text-sm">
            <legend className="mb-1 font-medium">{t(locale, "home.widgets")}</legend>
            {WIDGETS.map(([key, label]) => (
              <label key={key} className="me-4 inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={editing.widgets.includes(key)}
                  onChange={(e) =>
                    setDraft({ ...editing, widgets: e.target.checked ? [...editing.widgets, key] : editing.widgets.filter((x) => x !== key) })
                  }
                />
                {t(locale, label)}
              </label>
            ))}
          </fieldset>
          <fieldset className="mt-3 text-sm">
            <legend className="mb-1 font-medium">{t(locale, "home.panels")}</legend>
            {(["rooms", "compact"] as const).map((key) => (
              <label key={key} className="me-4 inline-flex items-center gap-2">
                <input type="checkbox" checked={editing.panels[key]} onChange={(e) => setDraft({ ...editing, panels: { ...editing.panels, [key]: e.target.checked } })} />
                {t(locale, `home.panel.${key}`)}
              </label>
            ))}
            <label className="me-4 inline-flex items-center gap-2">
              <input type="checkbox" checked={editing.panels.right_rail} onChange={(e) => setDraft({ ...editing, panels: { ...editing.panels, right_rail: e.target.checked } })} />
              {tr("Right rail (Your workspace)")}
            </label>
            {flag(access, "voice_video") ? (
              <label className="me-4 inline-flex items-center gap-2">
                <input type="checkbox" checked={editing.panels.video} onChange={(e) => setDraft({ ...editing, panels: { ...editing.panels, video: e.target.checked } })} />
                {tr("Camera panel")}
              </label>
            ) : null}
            <label className="inline-flex items-center gap-2">
              {t(locale, "home.accent")}
              <input type="color" value={editing.accent || "#a855f7"} onChange={(e) => setDraft({ ...editing, accent: e.target.value })} />
            </label>
          </fieldset>
          <label className="mt-3 flex items-center gap-2 text-sm">
            {tr("Rooms open on")}
            <select className="v2-input w-auto py-1" value={editing.default_room_tab} onChange={(e) => setDraft({ ...editing, default_room_tab: e.target.value })}>
              {ROOM_TABS.map((tab) => (
                <option key={tab} value={tab}>
                  {tr(ROOM_TAB_LABEL[tab])}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cockpit.low_bandwidth} onChange={(e) => save({ low_bandwidth: e.target.checked })} />
            {t(locale, "home.lowBandwidth")}
          </label>
          <Button
            className="mt-4"
            onClick={async () => {
              await save({ layout: editing });
              setDraft(null);
              setSaved(true);
            }}
          >
            {t(locale, "home.saveLayout")}
          </Button>
          {saved ? <Notice kind="ok">{t(locale, "home.saved")}</Notice> : null}
        </details>
      ) : null}

      <div className={cn("grid gap-4", layout.panels.compact ? "grid-cols-1" : "md:grid-cols-2 xl:grid-cols-3")}>
        {layout.widgets.map((key) => (widget[key] ? <div key={key}>{widget[key]}</div> : null))}
      </div>
    </div>
  );
}
