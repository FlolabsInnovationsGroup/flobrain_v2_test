"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiError, errorText } from "@/lib/v2/api";

type Suggestion = {
  user_id: string;
  username: string | null;
  score: number;
  reasons: { matched_skills: string[]; done_in_team: number; open_tasks: number };
};

/**
 * Assign people to a task. Leads and admins pick anyone they may assign (Decision 2); members
 * only themselves. "Suggest" asks the server who fits best and why; the person still decides.
 */
export function AssignPanel({
  orgId,
  taskId,
  canAssignOthers,
  selfId,
  assigned,
  members,
  onAssign,
}: {
  orgId: string | null;
  taskId: string;
  canAssignOthers: boolean;
  selfId: string | null;
  assigned: string[];
  members: Array<{ id: string; username: string | null }>;
  onAssign: (userId: string) => Promise<void> | void;
}) {
  const tr = useTr();
  const choices = members.filter((m) => !assigned.includes(m.id));
  const [userId, setUserId] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function suggest() {
    setNote(null);
    setBusy(true);
    try {
      const data = await api.get<{ suggestions: Suggestion[] }>(`/orgs/${orgId}/tasks/${taskId}/suggest-assignee`);
      setSuggestions(data.suggestions);
    } catch (err) {
      setSuggestions(null);
      setNote(apiError(err).status === 501 ? tr("Suggestions are switched off for your organization.") : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canAssignOthers) {
    if (!selfId || assigned.includes(selfId)) {
      return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("You can only assign yourself.")}</p>;
    }
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" onClick={() => onAssign(selfId)}>
          {tr("Assign to me")}
        </Button>
        <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("You can only assign yourself.")}</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (userId) {
            onAssign(userId);
            setUserId("");
          }
        }}
      >
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block font-medium">{tr("Assign to")}</span>
          <select className="v2-input" value={userId} onChange={(event) => setUserId(event.target.value)}>
            <option value="">{tr("Choose a person")}</option>
            {choices.map((member) => (
              <option key={member.id} value={member.id}>
                {member.username || member.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={!userId}>
          {tr("Assign")}
        </Button>
        <Button type="button" variant="ghost" onClick={suggest} disabled={busy || !orgId}>
          {busy ? tr("Thinking…") : tr("Suggest someone")}
        </Button>
      </form>
      {note ? <Notice>{note}</Notice> : null}
      {suggestions ? (
        suggestions.length === 0 ? (
          <Notice>{tr("No one else on the team is free to take this.")}</Notice>
        ) : (
          <ul className="space-y-2">
            {suggestions.map((s) => (
              <li key={s.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg p-2 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                <div className="text-sm">
                  <p className="font-medium">{s.username || s.user_id.slice(0, 8)}</p>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {s.reasons.matched_skills.length ? tr("Skills: {skills}", { skills: s.reasons.matched_skills.join(", ") }) + ". " : ""}
                    {tr("{done} done in this team, {open} open now", { done: s.reasons.done_in_team, open: s.reasons.open_tasks })}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone="neutral">{tr("Score {n}", { n: s.score })}</Badge>
                  <Button type="button" variant="outline" onClick={() => onAssign(s.user_id)}>
                    {tr("Assign")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
