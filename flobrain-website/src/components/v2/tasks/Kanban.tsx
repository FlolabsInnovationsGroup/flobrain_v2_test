"use client";

import { useMemo, useState } from "react";

import { Empty } from "@/components/v2/states";
import { AssignPanel } from "@/components/v2/tasks/AssignPanel";
import {
  KANBAN_COLUMNS,
  groupKanbanTasks,
  nextKanbanStatuses,
  type KanbanTask,
} from "@/lib/v2/screens/kanban";
import type { AssignActorRole } from "@/lib/v2/screens/assign";

export function Kanban({
  tasks = [],
  onMove,
  onAssign,
  members = [],
  role = "member",
  sameTeam = true,
}: {
  tasks?: KanbanTask[];
  onMove?: (id: string, status: string) => void;
  onAssign?: (taskId: string, userId: string) => void;
  members?: Array<{ id: string; username: string | null }>;
  role?: AssignActorRole;
  sameTeam?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [assignee, setAssignee] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const grouped = useMemo(
    () => groupKanbanTasks(tasks, { query, assignee: assignee || undefined }),
    [tasks, query, assignee],
  );
  const selectedTask = tasks.find((task) => task.id === selected) ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter tasks"
          className="rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-2 py-1"
        />
        <select
          value={assignee}
          onChange={(event) => setAssignee(event.target.value)}
          className="rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-2 py-1"
        >
          <option value="">All assignees</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.username || member.id}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {KANBAN_COLUMNS.map((column) => {
          const items = grouped[column.id];
          return (
            <section key={column.id} className="rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-surface)] p-3">
              <h2 className="mb-2 text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">
                {column.label}
              </h2>
              {items.length === 0 ? (
                <Empty />
              ) : (
                <ul className="space-y-2">
                  {items.map((task) => (
                    <li key={task.id}>
                      <button type="button" className="text-start" onClick={() => setSelected(task.id)}>
                        {task.title}
                      </button>
                      {onMove
                        ? nextKanbanStatuses(task.status).map((target) => (
                            <button
                              key={target.id}
                              type="button"
                              className="me-2 mt-1 text-xs text-[color:var(--fb-v2-accent)]"
                              onClick={() => onMove(task.id, target.id)}
                            >
                              Move to {target.label}
                            </button>
                          ))
                        : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      {selectedTask ? (
        <AssignPanel
          role={role}
          sameTeam={sameTeam}
          members={members}
          onAssign={(userId) => onAssign?.(selectedTask.id, userId)}
        />
      ) : null}
    </div>
  );
}
