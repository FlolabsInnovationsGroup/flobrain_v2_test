"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { AssignPanel } from "@/components/v2/tasks/AssignPanel";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { PRIORITIES, type TaskRow } from "@/lib/v2/screens/tasks";

export type TaskPatch = Partial<{
  title: string;
  description: string;
  priority: string;
  due_on: string | null;
  is_blocked: boolean;
  blocked_reason: string;
}>;

/** One task: edit it, block it with a reason, assign people, or delete it. */
export function TaskPanel({
  task,
  orgId,
  selfId,
  canAssignOthers,
  members,
  onClose,
  onSave,
  onAssign,
  onUnassign,
  onDelete,
  message,
}: {
  task: TaskRow;
  orgId: string | null;
  selfId: string | null;
  canAssignOthers: boolean;
  members: Array<{ id: string; username: string | null }>;
  onClose: () => void;
  onSave: (patch: TaskPatch) => Promise<boolean>;
  onAssign: (userId: string) => Promise<void> | void;
  onUnassign: (userId: string) => Promise<void> | void;
  onDelete: () => void;
  message: { kind: "ok" | "error"; text: string } | null;
}) {
  const tr = useTr();
  const [form, setForm] = useState({
    title: task.title,
    description: task.description ?? "",
    priority: task.priority,
    due_on: task.due_on ?? "",
  });
  const [reason, setReason] = useState(task.blocked_reason ?? "");
  const [confirming, setConfirming] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const editable = task.can_edit !== false;

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-panel-title"
        className="h-full w-full max-w-lg overflow-y-auto bg-[color:var(--fb-v2-page)] p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 id="task-panel-title" className="text-lg font-semibold">
            {task.title}
          </h2>
          <button ref={closeRef} type="button" aria-label={tr("Close")} className="rounded-md p-1 hover:bg-[color:var(--fb-v2-border)]" onClick={onClose}>
            <X aria-hidden className="size-5" />
          </button>
        </div>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        {!editable ? <Notice>{tr("You can see this task but only its assignees, its creator and the team lead can change it.")}</Notice> : null}

        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSave({ title: form.title, description: form.description, priority: form.priority, due_on: form.due_on || null });
          }}
        >
          <fieldset disabled={!editable}>
            <Field label={tr("Task name")}>
              <input className="v2-input" required maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </Field>
            <div className="grid gap-x-3 sm:grid-cols-2">
              <Field label={tr("Priority")}>
                <select className="v2-input" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  {PRIORITIES.map((p) => (
                    <option key={p.id} value={p.id}>
                      {tr(p.label)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={tr("Due date")} hint={canAssignOthers ? undefined : tr("Only the team lead changes due dates on tasks shared with others.")}>
                <input className="v2-input" type="date" value={form.due_on} onChange={(e) => setForm({ ...form, due_on: e.target.value })} />
              </Field>
            </div>
            <Field label={tr("Description")}>
              <textarea className="v2-input min-h-24" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <Button type="submit">{tr("Save changes")}</Button>
          </fieldset>
        </form>

        <section className="mt-8">
          <h3 className="mb-2 font-semibold">{tr("Blocked")}</h3>
          {task.is_blocked ? (
            <div className="space-y-2">
              <p className="text-sm">
                <Badge tone="bad">{tr("Blocked")}</Badge> {task.blocked_reason}
              </p>
              {task.blocked_since ? (
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Since {when}", { when: when(task.blocked_since) })}</p>
              ) : null}
              {editable ? (
                <Button type="button" variant="outline" onClick={() => onSave({ is_blocked: false })}>
                  {tr("Mark as unblocked")}
                </Button>
              ) : null}
            </div>
          ) : editable ? (
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                onSave({ is_blocked: true, blocked_reason: reason.trim() });
              }}
            >
              <label className="min-w-56 flex-1 text-sm">
                <span className="mb-1 block font-medium">{tr("What is it waiting for?")}</span>
                <input className="v2-input" required value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <Button type="submit" variant="waiting">
                {tr("Mark as blocked")}
              </Button>
            </form>
          ) : (
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Not blocked")}</p>
          )}
        </section>

        <section className="mt-8">
          <h3 className="mb-2 font-semibold">{tr("Assignees")}</h3>
          <ul className="mb-3 space-y-1">
            {task.people.length === 0 ? <li className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Nobody assigned")}</li> : null}
            {task.people.map((person) => (
              <li key={person.id} className="flex items-center justify-between text-sm">
                <span>{person.name}</span>
                {canAssignOthers || person.id === selfId ? (
                  <Button type="button" variant="ghost" onClick={() => onUnassign(person.id)}>
                    {tr("Remove")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          <AssignPanel
            orgId={orgId}
            taskId={task.id}
            canAssignOthers={canAssignOthers}
            selfId={selfId}
            assigned={task.assignees}
            members={members}
            onAssign={onAssign}
          />
        </section>

        {task.can_delete ? (
          <section className="mt-8 border-t border-[color:var(--fb-v2-border)] pt-4">
            {confirming ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm">{tr("Delete this task for everyone?")}</span>
                <Button type="button" variant="danger" onClick={onDelete}>
                  {tr("Delete task")}
                </Button>
                <Button type="button" variant="ghost" onClick={() => setConfirming(false)}>
                  {tr("Cancel")}
                </Button>
              </div>
            ) : (
              <Button type="button" variant="danger" onClick={() => setConfirming(true)}>
                {tr("Delete task")}
              </Button>
            )}
          </section>
        ) : null}
      </aside>
    </div>
  );
}
