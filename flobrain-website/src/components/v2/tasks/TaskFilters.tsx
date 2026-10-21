"use client";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { cn } from "@/lib/utils";
import { KANBAN_COLUMNS } from "@/lib/v2/screens/kanban";
import { activeFilterCount, EMPTY_FILTERS, type BoardFilters } from "@/lib/v2/screens/tasks";

const VIEWS: Array<{ id: BoardFilters["view"]; label: string }> = [
  { id: "all", label: "All" },
  { id: "mine", label: "My tasks" },
  { id: "assigned_by_me", label: "Assigned by me" },
  { id: "completed", label: "Completed" },
];

const DUE: Array<{ id: BoardFilters["due"]; label: string }> = [
  { id: "", label: "Any due date" },
  { id: "overdue", label: "Overdue" },
  { id: "today", label: "Due today" },
  { id: "week", label: "Due in 7 days" },
  { id: "none", label: "No due date" },
];

type Option = { id: string; name: string };

/** Decision 4 filters plus team, project, status, due date and blocked. */
export function TaskFilters({
  value,
  onChange,
  members,
  teams,
  projects,
}: {
  value: BoardFilters;
  onChange: (next: BoardFilters) => void;
  members: Option[];
  teams: Option[];
  projects: Option[];
}) {
  const tr = useTr();
  const set = (patch: Partial<BoardFilters>) => onChange({ ...value, ...patch });
  const count = activeFilterCount(value);
  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={tr("Show")}>
        {VIEWS.map((view) => (
          <button
            key={view.id}
            type="button"
            aria-pressed={value.view === view.id}
            onClick={() => set({ view: view.id })}
            className={cn(
              "rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]",
              value.view === view.id && "bg-[color:var(--fb-v2-accent)] text-white ring-transparent",
            )}
          >
            {tr(view.label)}
          </button>
        ))}
        <input
          type="search"
          value={value.query}
          onChange={(event) => set({ query: event.target.value })}
          placeholder={tr("Filter tasks")}
          aria-label={tr("Filter tasks")}
          className="v2-input ms-auto w-56 py-1"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select className="v2-input w-auto py-1" aria-label={tr("Assigned to")} value={value.assignee} onChange={(e) => set({ assignee: e.target.value })}>
          <option value="">{tr("All assignees")}</option>
          {members.map((m) => (
            <option key={m.id} value={m.id}>
              {tr("Assigned to {name}", { name: m.name })}
            </option>
          ))}
        </select>
        <select className="v2-input w-auto py-1" aria-label={tr("Team")} value={value.team} onChange={(e) => set({ team: e.target.value })}>
          <option value="">{tr("All teams")}</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        <select className="v2-input w-auto py-1" aria-label={tr("Project")} value={value.project} onChange={(e) => set({ project: e.target.value })}>
          <option value="">{tr("All projects")}</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select className="v2-input w-auto py-1" aria-label={tr("Status")} value={value.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">{tr("Every status")}</option>
          {KANBAN_COLUMNS.map((c) => (
            <option key={c.id} value={c.id}>
              {tr(c.label)}
            </option>
          ))}
        </select>
        <select
          className="v2-input w-auto py-1"
          aria-label={tr("Due date")}
          value={value.due}
          onChange={(e) => set({ due: e.target.value as BoardFilters["due"] })}
        >
          {DUE.map((d) => (
            <option key={d.id} value={d.id}>
              {tr(d.label)}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={value.blocked} onChange={(e) => set({ blocked: e.target.checked })} />
          {tr("Blocked only")}
        </label>
        {count ? (
          <Button type="button" variant="ghost" onClick={() => onChange({ ...EMPTY_FILTERS, query: value.query })}>
            {tr("Clear filters ({n})", { n: count })}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
