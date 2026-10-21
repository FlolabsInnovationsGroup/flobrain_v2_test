"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { cn } from "@/lib/utils";
import type { KanbanTask } from "@/lib/v2/screens/kanban";
import { dueState, priorityLabel, priorityTone } from "@/lib/v2/screens/tasks";

export function TaskCard({
  task,
  today,
  onOpen,
  children,
}: {
  task: KanbanTask;
  today: string;
  onOpen?: () => void;
  children?: React.ReactNode;
}) {
  const tr = useTr();
  const due = dueState({ due_on: task.due_on, status: task.status }, today);
  const names = (task.people ?? []).map((p) => p.name).filter(Boolean);
  return (
    <article
      className={cn(
        "rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]",
        task.is_blocked && "ring-[color:var(--fb-v2-error)]",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        {onOpen ? (
          <button type="button" className="text-start font-medium hover:underline" onClick={onOpen}>
            {task.title}
          </button>
        ) : (
          <p className="font-medium">{task.title}</p>
        )}
        {task.priority && task.priority !== "normal" ? <Badge tone={priorityTone(task.priority)}>{tr(priorityLabel(task.priority))}</Badge> : null}
      </div>
      {task.is_blocked ? (
        <p className="mt-2 text-xs">
          <Badge tone="bad">{tr("Blocked")}</Badge>{" "}
          <span className="text-[color:var(--fb-v2-text-muted)]">{task.blocked_reason || tr("No reason given")}</span>
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[color:var(--fb-v2-text-muted)]">
        {due ? (
          <span className={cn(due.late && "font-medium text-[color:var(--fb-v2-error)]", due.soon && "text-[color:var(--fb-v2-waiting)]")}>
            {tr(due.text, { n: due.n, date: task.due_on ?? "" })}
          </span>
        ) : null}
        <span>{names.length ? names.join(", ") : tr("Nobody assigned")}</span>
      </div>
      {children}
    </article>
  );
}
