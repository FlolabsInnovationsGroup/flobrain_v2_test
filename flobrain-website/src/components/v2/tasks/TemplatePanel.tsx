"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice, Row, Rows } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Template = { id: string; name: string; task_count: number };

/** Start a project from a template (its starter tasks land on the board), or save a new template. */
export function TemplatePanel({
  orgId,
  teams,
  onCreated,
}: {
  orgId: string | null;
  teams: Array<{ id: string; name: string }>;
  onCreated: () => void;
}) {
  const tr = useTr();
  const templates = useOrgData<Template[]>(orgId, "/project-templates");
  const [start, setStart] = useState({ template: "", name: "", team: "" });
  const [draft, setDraft] = useState({ name: "", tasks: "" });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const rows = templates.data ?? [];

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      templates.reload();
      onCreated();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="mb-6 grid gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 md:grid-cols-2">
      {message ? (
        <div className="md:col-span-2">
          <Notice kind={message.kind}>{message.text}</Notice>
        </div>
      ) : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          act(
            () =>
              api.post(`/orgs/${orgId}/projects/from-template`, {
                template_id: start.template,
                name: start.name.trim() || undefined,
                team: start.team || undefined,
              }),
            tr("Project created with its starter tasks."),
          );
        }}
      >
        <h2 className="mb-3 font-semibold">{tr("Start a project from a template")}</h2>
        {rows.length === 0 ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No templates yet. Save one on the right.")}</p>
        ) : (
          <>
            <Field label={tr("Template")}>
              <select className="v2-input" required value={start.template} onChange={(e) => setStart({ ...start, template: e.target.value })}>
                <option value="">{tr("Choose a template")}</option>
                {rows.map((t) => (
                  <option key={t.id} value={t.id}>
                    {tr("{name} ({n} tasks)", { name: t.name, n: t.task_count })}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={tr("Project name")} hint={tr("Leave empty to use the template's name.")}>
              <input className="v2-input" value={start.name} onChange={(e) => setStart({ ...start, name: e.target.value })} />
            </Field>
            <Field label={tr("Team")}>
              <select className="v2-input" value={start.team} onChange={(e) => setStart({ ...start, team: e.target.value })}>
                <option value="">{tr("No team")}</option>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
            <Button type="submit">{tr("Create project")}</Button>
          </>
        )}
      </form>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const tasks = draft.tasks
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((title) => ({ title }));
          act(() => api.post(`/orgs/${orgId}/project-templates`, { name: draft.name, spec: { tasks } }), tr("Template saved."));
          setDraft({ name: "", tasks: "" });
        }}
      >
        <h2 className="mb-3 font-semibold">{tr("Save a template")}</h2>
        <Field label={tr("Template name")}>
          <input className="v2-input" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </Field>
        <Field label={tr("Starter tasks")} hint={tr("One task per line.")}>
          <textarea className="v2-input min-h-24" value={draft.tasks} onChange={(e) => setDraft({ ...draft, tasks: e.target.value })} />
        </Field>
        <Button type="submit" variant="outline">
          {tr("Save template")}
        </Button>
        {rows.length ? (
          <div className="mt-4">
            <Rows>
              {rows.map((t) => (
                <Row key={t.id}>
                  <span className="text-sm">{t.name}</span>
                  <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} tasks", { n: t.task_count })}</span>
                </Row>
              ))}
            </Rows>
          </div>
        ) : null}
      </form>
    </div>
  );
}
