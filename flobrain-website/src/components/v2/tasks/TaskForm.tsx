"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { newTaskProblem, PRIORITIES, type NewTask } from "@/lib/v2/screens/tasks";

type Option = { id: string; name: string };

const BLANK: NewTask = { title: "", description: "", assignees: [], due_on: "", priority: "normal", team: "", project: "" };

/**
 * New task (Decision 5): name, assignees, due date, priority, team, project, description.
 * Members create tasks for themselves; leads and admins can pick other people.
 */
export function TaskForm({
  selfId,
  canAssignOthers,
  members,
  teams,
  projects,
  defaultTeam,
  inRoom,
  onCreate,
  onCancel,
}: {
  selfId: string | null;
  canAssignOthers: (team: string) => boolean;
  members: Array<{ id: string; username: string | null }>;
  teams: Option[];
  projects: Option[];
  defaultTeam?: string;
  inRoom: boolean;
  onCreate: (form: NewTask) => Promise<boolean>;
  onCancel: () => void;
}) {
  const tr = useTr();
  const [form, setForm] = useState<NewTask>({ ...BLANK, team: defaultTeam ?? "", assignees: selfId ? [selfId] : [] });
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const others = canAssignOthers(form.team);

  function toggle(id: string) {
    setForm((f) => ({ ...f, assignees: f.assignees.includes(id) ? f.assignees.filter((a) => a !== id) : [...f.assignees, id] }));
  }

  return (
    <form
      className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const ready = { ...form, assignees: others ? form.assignees : selfId ? [selfId] : [] };
        const issue = newTaskProblem(ready, selfId);
        setProblem(issue);
        if (issue) return;
        setBusy(true);
        const ok = await onCreate(ready);
        setBusy(false);
        if (ok) setForm({ ...BLANK, team: form.team, assignees: selfId ? [selfId] : [] });
      }}
    >
      <h2 className="mb-3 font-semibold">{tr("New task")}</h2>
      {problem ? <Notice kind="error">{tr(problem)}</Notice> : null}
      <div className="grid gap-x-3 md:grid-cols-2">
        <Field label={tr("Task name")}>
          <input className="v2-input" required maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-x-3">
          <Field label={tr("Due date")} hint={others ? tr("Needed when you assign someone else.") : undefined}>
            <input className="v2-input" type="date" value={form.due_on} onChange={(e) => setForm({ ...form, due_on: e.target.value })} />
          </Field>
          <Field label={tr("Priority")}>
            <select className="v2-input" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
              {PRIORITIES.map((p) => (
                <option key={p.id} value={p.id}>
                  {tr(p.label)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={tr("Team")} hint={inRoom ? tr("Leave empty to use the room's team.") : undefined}>
          <select className="v2-input" value={form.team} onChange={(e) => setForm({ ...form, team: e.target.value })}>
            <option value="">{tr("No team")}</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={tr("Project")}>
          <select className="v2-input" value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })}>
            <option value="">{tr("No project")}</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <fieldset className="mb-4">
        <legend className="mb-1 text-sm font-medium">{tr("Assignees")}</legend>
        {others ? (
          <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto">
            {members.map((m) => (
              <label
                key={m.id}
                className="flex items-center gap-2 rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] has-[:checked]:ring-[color:var(--fb-v2-accent)]"
              >
                <input type="checkbox" checked={form.assignees.includes(m.id)} onChange={() => toggle(m.id)} />
                {m.id === selfId ? tr("Me") : m.username || m.id.slice(0, 8)}
              </label>
            ))}
          </div>
        ) : (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("The task is yours. Only team leads and admins assign other people.")}</p>
        )}
      </fieldset>
      <Field label={tr("Description")}>
        <textarea className="v2-input min-h-20" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </Field>
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? tr("Creating…") : tr("Create task")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {tr("Cancel")}
        </Button>
      </div>
    </form>
  );
}
