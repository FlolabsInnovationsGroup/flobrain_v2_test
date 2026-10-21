"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { v2Client } from "@/lib/v2/client";

type Item = { id: string; text?: string; title?: string; owner?: string; task_id?: string };
type Member = { id: string; username: string };

/** Turn one meeting action item into a task: a person confirms who does it and by when. */
export function ActionItemTask({ orgId, orgSlug, meetingId, item, onDone }: { orgId: string; orgSlug: string; meetingId: string; item: Item; onDone: (text: string) => void }) {
  const tr = useTr();
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (item.task_id) {
    return (
      <Link className="text-sm underline" href={`/w/${orgSlug}/tasks`}>
        {tr("Task created")}
      </Link>
    );
  }

  async function start() {
    setOpen(true);
    try {
      const data = await v2Client().members(orgId);
      const rows = ((data.results ?? []) as Member[]).map((m) => ({ id: m.id, username: m.username }));
      setMembers(rows);
      const owner = (item.owner ?? "").toLowerCase();
      const match = owner ? rows.find((m) => m.username.toLowerCase().startsWith(owner)) : undefined;
      setAssignee(match?.id ?? "");
    } catch {
      setMembers([]);
    }
  }

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api.post(`/orgs/${orgId}/meetings/${meetingId}/action-items/${item.id}/to-task`, { confirm: true, assignee_id: assignee || null, due_on: due || null });
      setOpen(false);
      onDone(assignee ? tr("Task created and assigned.") : tr("Task created and assigned to you."));
    } catch (err) {
      setError(errorText(err));
    }
    setBusy(false);
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={start}>
        {tr("Make it a task")}
      </Button>
    );
  }
  return (
    <div className="flex w-full flex-wrap items-end gap-2 rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-sm">
      <label className="flex flex-col gap-1">
        <span>{tr("Who does it")}</span>
        <select className="v2-input" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
          <option value="">{tr("Me")}</option>
          {members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.username}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span>{tr("Due date (optional)")}</span>
        <input className="v2-input" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </label>
      <Button disabled={busy} onClick={confirm}>
        {tr("Create the task")}
      </Button>
      <Button variant="outline" onClick={() => setOpen(false)}>
        {tr("Cancel")}
      </Button>
      {error ? <p className="w-full text-[color:var(--fb-v2-error)]">{error}</p> : null}
    </div>
  );
}
