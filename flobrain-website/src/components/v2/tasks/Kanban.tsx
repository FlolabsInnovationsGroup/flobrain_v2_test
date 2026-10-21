"use client";

import { ArrowDown, ArrowUp, ChevronsLeftRight } from "lucide-react";
import { useMemo, useState } from "react";

import { TaskCard } from "@/components/v2/tasks/TaskCard";
import { useTr } from "@/i18n/phrases";
import { cn } from "@/lib/utils";
import { beforeForStep, groupKanbanTasks, KANBAN_COLUMNS, nextKanbanStatuses, type KanbanTask } from "@/lib/v2/screens/kanban";

type Drop = { status: string; before: string | null } | null;

/**
 * Three columns. Cards you can edit are draggable (HTML5 drag and drop) and also have buttons
 * to move between columns and up or down, so everything works from the keyboard.
 */
export function Kanban<T extends KanbanTask>({
  tasks = [],
  onMove,
  onOpen,
  query = "",
  today,
}: {
  tasks?: T[];
  onMove?: (id: string, status: string, before: string | null) => void;
  onOpen?: (id: string) => void;
  query?: string;
  today: string;
}) {
  const tr = useTr();
  const [dragging, setDragging] = useState<string | null>(null);
  const [drop, setDrop] = useState<Drop>(null);
  const grouped = useMemo(() => groupKanbanTasks(tasks, { query }), [tasks, query]);

  function finish(status: string, before: string | null) {
    if (dragging && onMove) {
      const task = tasks.find((t) => t.id === dragging);
      if (task && !(task.status === status && before === dragging)) onMove(dragging, status, before);
    }
    setDragging(null);
    setDrop(null);
  }

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {KANBAN_COLUMNS.map((column) => {
        const items = grouped[column.id];
        const isTarget = drop?.status === column.id;
        return (
          <section
            key={column.id}
            aria-label={tr(column.label)}
            className={cn(
              "flex min-h-40 flex-col rounded-xl bg-[color:var(--fb-v2-surface)] p-3 transition-shadow",
              isTarget && "ring-2 ring-inset ring-[color:var(--fb-v2-accent)]",
            )}
            onDragOver={(event) => {
              if (!dragging) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
              if (drop?.status !== column.id) setDrop({ status: column.id, before: null });
            }}
            onDrop={(event) => {
              event.preventDefault();
              finish(column.id, drop?.status === column.id ? drop.before : null);
            }}
          >
            <h2 className="mb-3 flex items-center justify-between text-sm font-semibold">
              {tr(column.label)}
              <span className="text-[color:var(--fb-v2-text-muted)]">{items.length}</span>
            </h2>
            <ul className="flex flex-1 flex-col gap-2">
              {items.map((task) => {
                const editable = task.can_edit !== false && !!onMove;
                return (
                  <li
                    key={task.id}
                    draggable={editable}
                    onDragStart={(event) => {
                      event.dataTransfer.setData("text/plain", task.id);
                      event.dataTransfer.effectAllowed = "move";
                      setDragging(task.id);
                    }}
                    onDragEnd={() => {
                      setDragging(null);
                      setDrop(null);
                    }}
                    onDragOver={(event) => {
                      if (!dragging) return;
                      event.preventDefault();
                      event.stopPropagation();
                      const box = event.currentTarget.getBoundingClientRect();
                      const after = event.clientY > box.top + box.height / 2;
                      const index = items.findIndex((t) => t.id === task.id);
                      const before = after ? (items[index + 1]?.id ?? null) : task.id;
                      if (drop?.status !== column.id || drop.before !== before) setDrop({ status: column.id, before });
                    }}
                    className={cn(
                      "rounded-lg",
                      dragging === task.id && "opacity-50",
                      isTarget && drop?.before === task.id && "shadow-[0_-3px_0_0_var(--fb-v2-accent)]",
                      editable && "cursor-grab active:cursor-grabbing",
                    )}
                  >
                    <TaskCard task={task} today={today} onOpen={onOpen ? () => onOpen(task.id) : undefined}>
                      {editable ? (
                        <div className="mt-2 flex flex-wrap items-center gap-1" role="group" aria-label={tr("Move “{title}”", { title: task.title })}>
                          {nextKanbanStatuses(task.status).map((target) => (
                            <button
                              key={target.id}
                              type="button"
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-[color:var(--fb-v2-accent)] hover:bg-[color:var(--fb-v2-border)]"
                              onClick={() => onMove?.(task.id, target.id, null)}
                            >
                              <ChevronsLeftRight aria-hidden className="size-3" />
                              {tr("Move to {status}", { status: tr(target.label) })}
                            </button>
                          ))}
                          <StepButton
                            label={tr("Move up")}
                            before={beforeForStep(items, task.id, -1)}
                            onPick={(before) => onMove?.(task.id, column.id, before)}
                            icon="up"
                          />
                          <StepButton
                            label={tr("Move down")}
                            before={beforeForStep(items, task.id, 1)}
                            onPick={(before) => onMove?.(task.id, column.id, before)}
                            icon="down"
                          />
                        </div>
                      ) : null}
                    </TaskCard>
                  </li>
                );
              })}
              {isTarget && drop?.before === null && items.length ? (
                <li aria-hidden className="h-1 rounded bg-[color:var(--fb-v2-accent)]" />
              ) : null}
              {items.length === 0 ? (
                <li className="flex flex-1 items-center justify-center rounded-lg p-4 text-sm text-[color:var(--fb-v2-text-muted)] border border-dashed border-[color:var(--fb-v2-border)]">
                  {dragging ? tr("Drop here") : tr("Nothing here")}
                </li>
              ) : null}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function StepButton({
  label,
  before,
  onPick,
  icon,
}: {
  label: string;
  before: string | null | undefined;
  onPick: (before: string | null) => void;
  icon: "up" | "down";
}) {
  const Icon = icon === "up" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={before === undefined}
      className="rounded-md p-1 text-[color:var(--fb-v2-text-muted)] hover:bg-[color:var(--fb-v2-border)] disabled:opacity-30"
      onClick={() => before !== undefined && onPick(before)}
    >
      <Icon aria-hidden className="size-3.5" />
    </button>
  );
}
