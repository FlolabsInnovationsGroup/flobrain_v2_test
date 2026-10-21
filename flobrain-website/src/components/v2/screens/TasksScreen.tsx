"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Kanban } from "@/components/v2/tasks/Kanban";
import { TaskFilters } from "@/components/v2/tasks/TaskFilters";
import { TaskForm } from "@/components/v2/tasks/TaskForm";
import { TaskPanel, type TaskPatch } from "@/components/v2/tasks/TaskPanel";
import { TemplatePanel } from "@/components/v2/tasks/TemplatePanel";
import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { KANBAN_COLUMNS, moveTask } from "@/lib/v2/screens/kanban";
import {
  activeFilterCount,
  canAssignOthersOn,
  EMPTY_FILTERS,
  localToday,
  newTaskBody,
  taskQuery,
  type BoardFilters,
  type NewTask,
  type TaskRow,
} from "@/lib/v2/screens/tasks";
import { useOrgData } from "@/lib/v2/useOrgData";

type Page<T> = { count?: number; next?: string | null; results: T[] };
type Member = { id: string; username: string | null; employment_status?: string };
type Option = { id: string; name: string };

export function TasksScreen({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const search = useSearchParams();
  const room = search.get("room");
  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS);
  // ``?task=`` opens that task (links from the calendar and Mission Control).
  const [open, setOpen] = useState<string | null>(() => search.get("task"));
  const [mode, setMode] = useState<"none" | "create" | "templates">("none");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [announce, setAnnounce] = useState("");
  const today = localToday();

  const query = useMemo(() => new URLSearchParams(taskQuery(filters, room)).toString(), [filters, room]);
  const tasks = useOrgData<Page<TaskRow>>(orgId, `/tasks?${query}`);
  const members = useOrgData<Page<Member>>(orgId, "/members?page_size=100");
  const teams = useOrgData<Option[]>(orgId, "/teams");
  const projects = useOrgData<Option[]>(orgId, "/projects");
  const roomInfo = useOrgData<{ name: string; team: string | null }>(orgId, room ? `/rooms/${room}` : null);

  const rows = useMemo(() => tasks.data?.results ?? [], [tasks.data]);
  const people = useMemo(
    () => rowsOf<Member>(members.data).filter((m) => !m.employment_status || m.employment_status === "active"),
    [members.data],
  );
  const options = useMemo(() => people.map((m) => ({ id: m.id, name: m.username || m.id.slice(0, 8) })), [people]);
  const selected = rows.find((t) => t.id === open) ?? null;
  const selfId = access?.user_id ?? null;
  const { setData, reload } = tasks;
  const truncated = (tasks.data?.count ?? 0) > rows.length;

  const act = useCallback(
    async (fn: () => Promise<unknown>, ok?: string) => {
      setMessage(null);
      try {
        await fn();
        if (ok) setMessage({ kind: "ok", text: ok });
        reload();
        return true;
      } catch (err) {
        setMessage({ kind: "error", text: errorText(err) });
        reload();
        return false;
      }
    },
    [reload],
  );

  const move = useCallback(
    (id: string, status: string, before: string | null) => {
      if (!orgId) return;
      const task = rows.find((t) => t.id === id);
      // Optimistic: the card moves now, and the server's order replaces it after the call.
      setData((current) => (current ? { ...current, results: moveTask(current.results, id, status, before) } : current));
      const column = KANBAN_COLUMNS.find((c) => c.id === status);
      if (task && column) setAnnounce(tr("Moved “{title}” to {status}", { title: task.title, status: tr(column.label) }));
      act(() => api.post(`/orgs/${orgId}/tasks/${id}/move`, { status, before }));
    },
    [orgId, rows, setData, act, tr],
  );

  async function create(form: NewTask) {
    return act(() => api.post(`/orgs/${orgId}/tasks`, newTaskBody(form, room)), tr("Task created."));
  }

  async function save(patch: TaskPatch) {
    return act(() => api.patch(`/orgs/${orgId}/tasks/${open}`, patch), tr("Saved."));
  }

  return (
    <div className="max-w-7xl">
      <PageHeader
        title={roomInfo.data ? tr("Tasks in {room}", { room: roomInfo.data.name }) : tr("Tasks")}
        intro={tr("Drag a card to another column or use its buttons. Blocked tasks show what they are waiting for.")}
        action={
          <div className="flex flex-wrap gap-2">
            {has(access, "project.manage") ? (
              <Button type="button" variant="outline" onClick={() => setMode(mode === "templates" ? "none" : "templates")}>
                {tr("Project templates")}
              </Button>
            ) : null}
            {has(access, "task.write") ? (
              <Button type="button" onClick={() => setMode(mode === "create" ? "none" : "create")}>
                {tr("New task")}
              </Button>
            ) : null}
          </div>
        }
      />
      {room ? (
        <Notice>
          {tr("Showing this room's board.")}{" "}
          <Link className="underline" href={`/w/${orgSlug}/tasks`}>
            {tr("Show all tasks")}
          </Link>
        </Notice>
      ) : null}
      {message && !open ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      {mode === "create" ? (
        <TaskForm
          selfId={selfId}
          canAssignOthers={(team) => canAssignOthersOn(access, team || roomInfo.data?.team || null)}
          members={people}
          teams={teams.data ?? []}
          projects={projects.data ?? []}
          inRoom={!!room}
          onCreate={create}
          onCancel={() => setMode("none")}
        />
      ) : null}
      {mode === "templates" ? <TemplatePanel orgId={orgId} teams={teams.data ?? []} onCreated={reload} /> : null}

      <TaskFilters value={filters} onChange={setFilters} members={options} teams={teams.data ?? []} projects={projects.data ?? []} />
      <ScreenBody state={tasks.state} error={tasks.error || tr("Could not load tasks")} onRetry={reload}>
        {rows.length === 0 ? (
          <Notice>{activeFilterCount(filters) === 0 && !filters.query ? tr("No tasks yet. Create one to get started.") : tr("No tasks match these filters.")}</Notice>
        ) : null}
        {truncated ? <Notice>{tr("Showing the first {n} tasks. Narrow the filters to see the rest.", { n: rows.length })}</Notice> : null}
        <Kanban tasks={rows} query={filters.query} today={today} onMove={move} onOpen={setOpen} />
      </ScreenBody>

      {selected ? (
        <TaskPanel
          key={selected.id}
          task={selected}
          orgId={orgId}
          selfId={selfId}
          canAssignOthers={canAssignOthersOn(access, selected.team)}
          members={people}
          message={message}
          onClose={() => {
            setOpen(null);
            setMessage(null);
          }}
          onSave={save}
          onAssign={(userId) => {
            act(() => api.post(`/orgs/${orgId}/tasks/${selected.id}/assign`, { user_id: userId }), tr("Assigned. They get a notification."));
          }}
          onUnassign={(userId) => {
            act(() => api.post(`/orgs/${orgId}/tasks/${selected.id}/unassign`, { user_id: userId }), tr("Removed from the task."));
          }}
          onDelete={async () => {
            const ok = await act(() => api.del(`/orgs/${orgId}/tasks/${selected.id}`), tr("Task deleted."));
            if (ok) setOpen(null);
          }}
        />
      ) : null}
    </div>
  );
}
