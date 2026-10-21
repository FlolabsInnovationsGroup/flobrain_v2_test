"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { CATEGORIES, fromLocalInput, manualEntryProblem, toLocalInput, type TimeEntryRow } from "@/lib/v2/screens/time";

type Option = { id: string; name: string };

export type EntryBody = {
  description: string;
  category: string;
  task: string | null;
  project: string | null;
  started_at?: string;
  ended_at?: string;
};

/** Add time you didn't track with the timer, or change one of your entries. */
export function EntryForm({
  entry,
  tasks,
  projects,
  onSubmit,
  onCancel,
}: {
  entry?: TimeEntryRow;
  tasks: Option[];
  projects: Option[];
  onSubmit: (body: EntryBody) => Promise<boolean>;
  onCancel?: () => void;
}) {
  const tr = useTr();
  const running = !!entry && !entry.ended_at;
  const [form, setForm] = useState({
    description: entry?.description ?? "",
    category: entry?.category ?? "projects",
    task: entry?.task ?? "",
    project: entry?.project ?? "",
    start: toLocalInput(entry?.started_at),
    end: toLocalInput(entry?.ended_at),
  });
  const [problem, setProblem] = useState<string | null>(null);

  return (
    <form
      className="grid gap-x-3 sm:grid-cols-2 lg:grid-cols-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const body: EntryBody = {
          description: form.description,
          category: form.category,
          task: form.task || null,
          project: form.project || null,
        };
        if (!running) {
          const issue = manualEntryProblem(form.start, form.end);
          setProblem(issue);
          if (issue) return;
          body.started_at = fromLocalInput(form.start);
          body.ended_at = fromLocalInput(form.end);
        }
        const ok = await onSubmit(body);
        if (ok && !entry) setForm({ ...form, description: "", start: "", end: "" });
      }}
    >
      {problem ? (
        <div className="sm:col-span-2 lg:col-span-3">
          <Notice kind="error">{tr(problem)}</Notice>
        </div>
      ) : null}
      {!running ? (
        <>
          <Field label={tr("Start")}>
            <input className="v2-input" type="datetime-local" required value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
          </Field>
          <Field label={tr("End")}>
            <input className="v2-input" type="datetime-local" required value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
          </Field>
        </>
      ) : null}
      <Field label={tr("Category")}>
        <select className="v2-input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
          {CATEGORIES.map((c) => (
            <option key={c.id} value={c.id}>
              {tr(c.label)}
            </option>
          ))}
        </select>
      </Field>
      <Field label={tr("Description")}>
        <input className="v2-input" maxLength={2000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </Field>
      <Field label={tr("Task")}>
        <select className="v2-input" value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })}>
          <option value="">{tr("No task")}</option>
          {tasks.map((t) => (
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
      <div className="flex items-center gap-2 sm:col-span-2 lg:col-span-3">
        <Button type="submit">{entry ? tr("Save changes") : tr("Add time")}</Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {tr("Cancel")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}
