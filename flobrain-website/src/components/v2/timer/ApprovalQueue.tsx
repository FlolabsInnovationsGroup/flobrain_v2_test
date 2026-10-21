"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { categoryLabel, formatDuration, type TimeEntryRow } from "@/lib/v2/screens/time";
import { useOrgData } from "@/lib/v2/useOrgData";

/** Leads and admins: submitted time from the people they lead. */
export function ApprovalQueue({ orgId }: { orgId: string | null }) {
  const tr = useTr();
  const queue = useOrgData<TimeEntryRow[]>(orgId, "/time-entries/approvals", { list: true });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function decide(id: string, decision: "approve" | "reject") {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/time-entries/${id}/${decision}`, { note: notes[id] ?? "" });
      setMessage({ kind: "ok", text: decision === "approve" ? tr("Approved.") : tr("Sent back with your note.") });
      queue.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <Section title={tr("Waiting for your approval")}>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={queue.state} error={queue.error} emptyLabel={tr("Nothing waiting for you.")} onRetry={queue.reload}>
        <Rows>
          {(queue.data ?? []).map((entry) => (
            <Row key={entry.id}>
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {entry.user_name} · <span className="font-mono tabular-nums">{formatDuration(entry.seconds)}</span>
                </p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {when(entry.started_at)} · {tr(categoryLabel(entry.category))}
                  {entry.task_title ? ` · ${entry.task_title}` : ""}
                  {entry.project_name ? ` · ${entry.project_name}` : ""}
                </p>
                <p className="text-sm">
                  {entry.description_hidden ? <Badge>{tr("Details kept private")}</Badge> : entry.description || tr("No description")}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  className="v2-input w-48 py-1"
                  placeholder={tr("Note (needed to send back)")}
                  aria-label={tr("Note for {name}", { name: entry.user_name ?? "" })}
                  value={notes[entry.id] ?? ""}
                  onChange={(e) => setNotes({ ...notes, [entry.id]: e.target.value })}
                />
                <Button type="button" onClick={() => decide(entry.id, "approve")}>
                  {tr("Approve")}
                </Button>
                <Button type="button" variant="outline" disabled={!(notes[entry.id] ?? "").trim()} onClick={() => decide(entry.id, "reject")}>
                  {tr("Send back")}
                </Button>
              </div>
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </Section>
  );
}
