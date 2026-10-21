"use client";

import { useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Policy = {
  messages_days: number | null;
  recordings_days: number | null;
  transcripts_days: number | null;
  time_entries_days: number | null;
  can_edit: boolean;
  last_run_at: string | null;
  last_run_summary: Record<string, number>;
};
type Request = { id: string; status: string; reason: string; created_at: string; decided_at: string | null; user: { id: string; username: string }; summary: Record<string, number> };

const FIELDS: { key: keyof Policy; label: string }[] = [
  { key: "messages_days", label: "Room messages" },
  { key: "recordings_days", label: "Meeting recordings" },
  { key: "transcripts_days", label: "Meeting transcripts" },
  { key: "time_entries_days", label: "Time entries" },
];

const KINDS: Record<string, string> = { messages: "messages", recordings: "recordings", transcripts: "transcripts", summaries: "meeting summaries", time_entries: "time entries" };

/** Retention (owner sets it) and deletion requests (admins decide them). */
export default function RetentionPage() {
  const { orgId } = useAccess();
  const tr = useTr();
  const policy = useOrgData<Policy>(orgId, "/privacy/retention");
  const requests = useOrgData<Request[]>(orgId, "/privacy/deletion-requests?scope=all", { list: true });
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!policy.data) return;
    const p = policy.data;
    // Mirror the saved policy into the form once it arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm(Object.fromEntries(FIELDS.map(({ key }) => [key, p[key] == null ? "" : String(p[key])])));
  }, [policy.data]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    const body = Object.fromEntries(FIELDS.map(({ key }) => [key, form[key] ? Number(form[key]) : null]));
    try {
      await api.put(`/orgs/${orgId}/privacy/retention`, body);
      setMessage({ kind: "ok", text: tr("Retention saved. The daily cleanup applies it.") });
      policy.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function decide(id: string, decision: "approve" | "reject") {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/privacy/deletion-requests/${id}`, { decision });
      setMessage({ kind: "ok", text: decision === "approve" ? tr("Their data in this organization was erased.") : tr("Request rejected. They were told.") });
      requests.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const open = rowsOf<Request>(requests.data).filter((r) => r.status === "pending");
  const closed = rowsOf<Request>(requests.data).filter((r) => r.status !== "pending");

  return (
    <div className="max-w-3xl">
      <PageHeader title={tr("Retention and deletion")} intro={tr("How long this organization keeps its data, and requests from people to erase theirs.")} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      <Section title={tr("Deletion requests")}>
        <ScreenBody state={requests.state} error={requests.error} emptyLabel={tr("No one has asked for deletion.")} onRetry={requests.reload}>
          <Rows>
            {open.map((r) => (
              <Row key={r.id}>
                <div className="min-w-0">
                  <p className="font-medium">{r.user.username}</p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {tr("Asked {date}", { date: when(r.created_at) })}
                    {r.reason ? `: “${r.reason}”` : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button variant="danger" onClick={() => decide(r.id, "approve")}>
                    {tr("Erase their data")}
                  </Button>
                  <Button variant="outline" onClick={() => decide(r.id, "reject")}>
                    {tr("Reject")}
                  </Button>
                </div>
              </Row>
            ))}
            {closed.map((r) => (
              <Row key={r.id}>
                <span>
                  {r.status === "done"
                    ? tr("{name}: erased {date}", { name: r.user.username, date: when(r.decided_at) })
                    : tr("{name}: rejected {date}", { name: r.user.username, date: when(r.decided_at) })}
                </span>
                {r.status === "done" ? (
                  <span className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {tr("{m} messages, {c} AI conversations", { m: r.summary.messages ?? 0, c: r.summary.ai_conversations ?? 0 })}
                  </span>
                ) : null}
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>

      <Section title={tr("Retention")}>
        <ScreenBody state={policy.state} error={policy.error} onRetry={policy.reload}>
          {policy.data ? (
            <form onSubmit={save} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr("Days to keep each kind of data, from 7 to 3650. Leave a box empty to keep it forever. Deleting also removes it from org search, and meeting summaries go with their transcripts. Suggested: recordings 90, transcripts 365.")}
                {policy.data.can_edit ? "" : ` ${tr("Only the owner can change these.")}`}
              </p>
              <div className="grid gap-x-4 sm:grid-cols-2">
                {FIELDS.map(({ key, label }) => (
                  <Field key={key} label={tr(label)}>
                    <input
                      className="v2-input"
                      type="number"
                      min={7}
                      max={3650}
                      placeholder={tr("Keep forever")}
                      disabled={!policy.data?.can_edit}
                      value={form[key] ?? ""}
                      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                    />
                  </Field>
                ))}
              </div>
              {policy.data.can_edit ? <Button type="submit">{tr("Save retention")}</Button> : null}
              {policy.data.last_run_at ? (
                <p className="mt-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("Last cleanup {date}: {what}.", {
                    date: when(policy.data.last_run_at),
                    what:
                      Object.entries(policy.data.last_run_summary)
                        .map(([k, v]) => `${v} ${tr(KINDS[k] ?? k)}`)
                        .join(", ") || tr("nothing to remove"),
                  })}
                </p>
              ) : null}
            </form>
          ) : null}
        </ScreenBody>
      </Section>
    </div>
  );
}
