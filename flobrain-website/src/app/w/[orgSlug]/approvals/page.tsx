"use client";

import { useState } from "react";

import { ProposalEditor, type ToolSchema } from "@/components/v2/ai/ProposalEditor";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Proposal = {
  id: string;
  label: string;
  summary: string;
  arguments: Record<string, unknown>;
  edited?: boolean;
  schema?: ToolSchema;
  status: string;
  error: string;
  expires_at: string;
  created_at: string;
};

const STATUS: Record<string, { label: string; tone: "waiting" | "good" | "bad" | "neutral" }> = {
  proposed: { label: "Waiting for you", tone: "waiting" },
  executed: { label: "Done", tone: "good" },
  rejected: { label: "Rejected", tone: "neutral" },
  approved: { label: "Approved", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
  expired: { label: "Expired", tone: "neutral" },
};

export default function ApprovalsPage() {
  const { orgId } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<Proposal[]>(orgId, "/actions", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rows = rowsOf<Proposal>(data);
  const waiting = rows.filter((row) => row.status === "proposed");
  const done = rows.filter((row) => row.status !== "proposed");

  async function decide(id: string, decision: "approve" | "reject", edited?: Record<string, unknown>) {
    setMessage(null);
    setBusy(true);
    try {
      const result = await api.post<Proposal>(`/orgs/${orgId}/actions/${id}/${decision}`, edited ? { arguments: edited } : {});
      setMessage({
        kind: result.status === "failed" ? "error" : "ok",
        text:
          decision === "reject"
            ? tr("Rejected. Nothing was changed.")
            : result.status === "failed"
              ? tr("Approved, but it failed: {error}", { error: result.error })
              : tr("Approved: {summary}", { summary: result.summary }),
      });
      setEditing(null);
      window.dispatchEvent(new Event("flobrain:approvals-changed"));
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit(id: string, edited: Record<string, unknown>) {
    setMessage(null);
    setBusy(true);
    try {
      const result = await api.patch<Proposal>(`/orgs/${orgId}/actions/${id}`, { arguments: edited });
      setMessage({ kind: "ok", text: tr("Changes saved. It still waits for your approval: {summary}", { summary: result.summary }) });
      setEditing(null);
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Approvals")}
        intro={tr("Buddies and agents never change anything on their own. They propose an action, and it runs only after you approve it, with your permissions.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("Nothing to approve. When a buddy proposes an action, it shows up here.")} onRetry={reload}>
        <h2 className="mb-3 text-lg font-semibold">{tr("Waiting for you ({n})", { n: waiting.length })}</h2>
        {waiting.length === 0 ? <Notice>{tr("You're all caught up.")}</Notice> : null}
        <Rows>
          {waiting.map((row) => (
            <Row key={row.id}>
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {row.summary} {row.edited ? <Badge>{tr("Edited")}</Badge> : null}
                </p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("{label}. Proposed {created}. Expires {expires}.", { label: row.label, created: when(row.created_at), expires: when(row.expires_at) })}
                </p>
                {typeof row.arguments.body === "string" && editing !== row.id ? (
                  <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-sm">{row.arguments.body}</p>
                ) : null}
              </div>
              {editing === row.id ? null : (
                <div className="flex gap-2">
                  <Button variant="waiting" disabled={busy} onClick={() => decide(row.id, "approve")}>
                    {tr("Approve")}
                  </Button>
                  {row.schema?.properties ? (
                    <Button variant="outline" disabled={busy} onClick={() => setEditing(row.id)}>
                      {tr("Edit")}
                    </Button>
                  ) : null}
                  <Button variant="outline" disabled={busy} onClick={() => decide(row.id, "reject")}>
                    {tr("Reject")}
                  </Button>
                </div>
              )}
              {editing === row.id && row.schema ? (
                <ProposalEditor
                  schema={row.schema}
                  initial={row.arguments}
                  busy={busy}
                  onSave={(args) => saveEdit(row.id, args)}
                  onApprove={(args) => decide(row.id, "approve", args)}
                  onCancel={() => setEditing(null)}
                />
              ) : null}
            </Row>
          ))}
        </Rows>
        {done.length ? (
          <>
            <h2 className="mb-3 mt-8 text-lg font-semibold">{tr("History")}</h2>
            <Rows>
              {done.map((row) => (
                <Row key={row.id}>
                  <div className="min-w-0 flex-1">
                    <p>
                      {row.summary} {row.edited ? <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("(edited before approval)")}</span> : null}
                    </p>
                    {row.error ? <p className="text-sm text-[color:var(--fb-v2-error)]">{row.error}</p> : null}
                  </div>
                  <Badge tone={STATUS[row.status]?.tone ?? "neutral"}>{STATUS[row.status] ? tr(STATUS[row.status].label) : row.status}</Badge>
                </Row>
              ))}
            </Rows>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
