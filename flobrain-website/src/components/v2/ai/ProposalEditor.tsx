"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Prop = { type?: string; format?: string; enum?: string[]; maxLength?: number; items?: Prop };
export type ToolSchema = { properties?: Record<string, Prop>; required?: string[] };
type Option = { id: string; name?: string; username?: string };

const LABELS: Record<string, string> = {
  title: "Title",
  description: "Description",
  team: "Team",
  project: "Project",
  due_on: "Due date",
  room: "Room",
  body: "Message",
  starts_at: "Starts at",
  to: "To",
  subject: "Subject",
  hashtags: "Hashtags",
  scheduled_at: "Scheduled for",
  status: "Status",
  user: "Assignee",
  kind: "Kind",
  task: "Task",
  render: "Render",
  social_account: "Social account",
};
const VALUES: Record<string, string> = {
  to_do: "To Do",
  in_progress: "In Progress",
  done: "Done",
  daily_standup: "Daily standup",
  weekly_report: "Weekly report",
};
/** Id fields a person can re-pick here; other ids (a task, a render) stay as the buddy proposed. */
const PICKABLE: Record<string, string> = { room: "/rooms", team: "/teams", project: "/projects", user: "/members?page_size=100" };

function localInput(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Edit a proposal's arguments before approving (spec 8.6). The fields come from the tool's schema;
 * the server checks the edited values with the same rules as the proposal.
 */
export function ProposalEditor({
  schema,
  initial,
  onSave,
  onApprove,
  onCancel,
  busy,
}: {
  schema: ToolSchema;
  initial: Record<string, unknown>;
  onSave: (args: Record<string, unknown>) => void;
  onApprove: (args: Record<string, unknown>) => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const tr = useTr();
  const { orgId } = useAccess();
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const [values, setValues] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const [name, p] of Object.entries(props)) {
      const v = initial[name];
      if (v === undefined || v === null) out[name] = "";
      else if (Array.isArray(v)) out[name] = v.join(", ");
      else if (p.format === "date-time") out[name] = localInput(String(v));
      else out[name] = String(v);
    }
    return out;
  });
  const rooms = useOrgData<Option[]>(orgId, "room" in props ? PICKABLE.room : null);
  const teams = useOrgData<Option[]>(orgId, "team" in props ? PICKABLE.team : null);
  const projects = useOrgData<Option[]>(orgId, "project" in props ? PICKABLE.project : null);
  const members = useOrgData<{ results: Option[] }>(orgId, "user" in props ? PICKABLE.user : null);
  const options: Record<string, Option[]> = {
    room: rowsOf<Option>(rooms.data),
    team: rowsOf<Option>(teams.data),
    project: rowsOf<Option>(projects.data),
    user: rowsOf<Option>(members.data),
  };

  function args(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const [name, p] of Object.entries(props)) {
      const raw = (values[name] ?? "").trim();
      if (!raw) continue;
      if (p.type === "array") out[name] = raw.split(",").map((s) => s.trim()).filter(Boolean);
      else if (p.format === "date-time") out[name] = new Date(raw).toISOString();
      else out[name] = raw;
    }
    return out;
  }

  function input(name: string, p: Prop) {
    const set = (v: string) => setValues({ ...values, [name]: v });
    const value = values[name] ?? "";
    const isRequired = required.has(name);
    if (p.enum) {
      return (
        <select className="v2-input" value={value} required={isRequired} onChange={(e) => set(e.target.value)}>
          {!isRequired ? <option value="">{tr("None")}</option> : null}
          {p.enum.map((v) => (
            <option key={v} value={v}>
              {VALUES[v] ? tr(VALUES[v]) : v}
            </option>
          ))}
        </select>
      );
    }
    if (p.format === "uuid") {
      if (!(name in PICKABLE)) {
        return <input className="v2-input" value={value} readOnly aria-readonly />;
      }
      const list = options[name];
      const known = list.some((o) => o.id === value);
      return (
        <select className="v2-input" value={value} required={isRequired} onChange={(e) => set(e.target.value)}>
          {!isRequired ? <option value="">{tr("None")}</option> : null}
          {value && !known ? <option value={value}>{tr("As proposed")}</option> : null}
          {list.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name || o.username || o.id.slice(0, 8)}
            </option>
          ))}
        </select>
      );
    }
    if (p.format === "date") return <input className="v2-input" type="date" value={value} required={isRequired} onChange={(e) => set(e.target.value)} />;
    if (p.format === "date-time") return <input className="v2-input" type="datetime-local" value={value} required={isRequired} onChange={(e) => set(e.target.value)} />;
    if (p.type === "string" && (p.maxLength ?? 0) > 300) {
      return <textarea className="v2-input min-h-24" maxLength={p.maxLength} required={isRequired} value={value} onChange={(e) => set(e.target.value)} />;
    }
    return <input className="v2-input" maxLength={p.maxLength} required={isRequired} value={value} onChange={(e) => set(e.target.value)} />;
  }

  return (
    <form
      className="mt-3 w-full rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]"
      onSubmit={(e) => {
        e.preventDefault();
        onApprove(args());
      }}
    >
      <div className="grid gap-x-4 sm:grid-cols-2">
        {Object.entries(props).map(([name, p]) => (
          <div key={name} className={p.type === "string" && (p.maxLength ?? 0) > 300 ? "sm:col-span-2" : undefined}>
            <Field
              label={`${LABELS[name] ? tr(LABELS[name]) : name}${required.has(name) ? " *" : ""}`}
              hint={p.type === "array" ? tr("Comma separated") : p.format === "uuid" && !(name in PICKABLE) ? tr("Can't be changed here") : undefined}
            >
              {input(name, p)}
            </Field>
          </div>
        ))}
      </div>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Your changes are checked with the same rules and your permissions before anything runs.")}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="waiting" disabled={busy}>
          {tr("Approve with changes")}
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => onSave(args())}>
          {tr("Save changes")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {tr("Cancel")}
        </Button>
      </div>
    </form>
  );
}
