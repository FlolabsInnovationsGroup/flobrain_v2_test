"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Kanban } from "@/components/v2/tasks/Kanban";
import { v2Client } from "@/lib/v2/client";
import type { DirectoryMember } from "@/lib/v2/screens/directory";
import type { KanbanTask } from "@/lib/v2/screens/kanban";
import { isEmptyList, screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function TasksScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [members, setMembers] = useState<DirectoryMember[]>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    Promise.all([v2Client().tasks(orgId), v2Client().members(orgId)])
      .then(([taskData, memberData]) => {
        setTasks((taskData.results ?? []) as KanbanTask[]);
        setMembers((memberData.results ?? []) as DirectoryMember[]);
        setState(screenStateFromHttp(200, isEmptyList(taskData)));
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load tasks");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Tasks</h1>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No tasks yet" onRetry={load}>
        <Kanban
          tasks={tasks}
          members={members.map((member) => ({ id: member.id, username: member.username }))}
          onMove={(id, status) => {
            if (!orgId) return;
            v2Client().moveTask(orgId, id, status).then(load);
          }}
          onAssign={(taskId, userId) => {
            if (!orgId) return;
            v2Client().assignTask(orgId, taskId, userId).then(load);
          }}
        />
      </ScreenBody>
    </section>
  );
}
