"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Privacy = {
  settings: { share_time_details_with_org: boolean; analytics_personal_only: boolean; consents: Record<string, boolean> };
  data: Record<string, number>;
  who_can_see: { team_leads: string[]; owners_and_admins: number; rules: string[] };
};
type DataExport = { id: string; status: string; size_bytes: number; created_at: string; expires_at: string | null };
type DeletionRequest = { id: string; status: string; reason: string; created_at: string; decided_at: string | null };

const LABELS: Record<string, string> = {
  room_messages: "Messages you wrote in rooms",
  document_edits: "Document edits",
  task_assignments: "Tasks assigned to you",
  time_entries: "Time entries",
  ai_conversations: "Your private AI conversations",
  ai_usage_records: "AI usage records (counts and cost, no content)",
  ai_traces: "AI quality traces (ids and timings, no content)",
};

const STATUS: Record<string, string> = { queued: "Queued", running: "Working on it", succeeded: "Ready", failed: "Failed" };

/** The privacy center (Decision 44): what we hold about you, who sees it, and what you control. */
export default function PrivacyPage() {
  const { orgId } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<Privacy>(orgId, "/me/privacy");
  const exports = useOrgData<DataExport[]>(orgId, "/me/data-exports", { orgScoped: false, list: true });
  const requests = useOrgData<DeletionRequest[]>(orgId, "/privacy/deletion-requests", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);

  async function save(patch: Partial<Privacy["settings"]>) {
    setMessage(null);
    try {
      await api.put(`/orgs/${orgId}/me/privacy`, patch);
      setMessage({ kind: "ok", text: tr("Saved.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function startExport() {
    setMessage(null);
    try {
      await api.post("/me/data-exports");
      setMessage({ kind: "ok", text: tr("We're putting your data together. It appears below when it's ready.") });
      exports.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function download(id: string) {
    try {
      const res = await api.get<{ download_url?: string }>(`/me/data-exports/${id}`);
      if (res.download_url) window.location.assign(res.download_url);
      else setMessage({ kind: "error", text: tr("This copy has expired or isn't ready yet.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function requestDeletion() {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/privacy/deletion-requests`, { reason });
      setMessage({ kind: "ok", text: tr("Request sent. An admin decides it, and you'll get a notification.") });
      setConfirming(false);
      setReason("");
      requests.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const pendingRequest = rowsOf<DeletionRequest>(requests.data).find((r) => r.status === "pending");

  return (
    <div className="max-w-3xl">
      <PageHeader title={tr("Privacy")} intro={tr("What FloBrain keeps about you in this organization, who can see it, and what you control.")} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data ? (
          <>
            <Section title={tr("What we keep")}>
              <Rows>
                {Object.entries(data.data).map(([key, count]) => (
                  <Row key={key}>
                    <span>{LABELS[key] ? tr(LABELS[key]) : key}</span>
                    <span className="font-semibold tabular-nums">{count}</span>
                  </Row>
                ))}
              </Rows>
            </Section>

            <Section title={tr("Who can see it")}>
              <ul className="space-y-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm">
                {data.who_can_see.rules.map((rule) => (
                  <li key={rule}>{tr(rule)}</li>
                ))}
              </ul>
              <p className="mt-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                {data.who_can_see.team_leads.length ? tr("Your team leads: {names}.", { names: data.who_can_see.team_leads.join(tr(", ")) }) : tr("You have no team lead here.")}{" "}
                {tr("{n} owners and admins.", { n: data.who_can_see.owners_and_admins })}
              </p>
            </Section>

            <Section title={tr("Your choices")}>
              <div className="space-y-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                <label className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={data.settings.share_time_details_with_org}
                    onChange={(e) => save({ share_time_details_with_org: e.target.checked })}
                  />
                  <span>
                    <span className="block font-medium">{tr("Share what I worked on")}</span>
                    <span className="block text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("Off: your team leads still see your hours, but not the description of each time entry.")}
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={data.settings.analytics_personal_only}
                    onChange={(e) => save({ analytics_personal_only: e.target.checked })}
                  />
                  <span>
                    <span className="block font-medium">{tr("Keep my insights personal")}</span>
                    <span className="block text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("On: you're left out of team insights and of the organization's usage analytics. Your own Insights page still works.")}
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={data.settings.consents.product_analytics !== false}
                    onChange={(e) => save({ consents: { ...data.settings.consents, product_analytics: e.target.checked } })}
                  />
                  <span>
                    <span className="block font-medium">{tr("Help improve FloBrain")}</span>
                    <span className="block text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Anonymous usage counts, never the content of your work.")}</span>
                  </span>
                </label>
              </div>
            </Section>
          </>
        ) : null}
      </ScreenBody>

      <Section title={tr("Download your data")} aside={<Button variant="outline" onClick={startExport}>{tr("Prepare a copy")}</Button>}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("One zip with your profile, messages you wrote, tasks, time, AI conversations, certificates and more, from every organization you belong to.")}
        </p>
        <Rows>
          {rowsOf<DataExport>(exports.data).map((e) => (
            <Row key={e.id}>
              <span>
                {when(e.created_at)}
                {e.status === "succeeded" ? `, ${tr("{kb} KB, until {date}", { kb: (e.size_bytes / 1024).toFixed(0), date: when(e.expires_at) })}` : ""}
              </span>
              {e.status === "succeeded" ? (
                <Button variant="outline" onClick={() => download(e.id)}>
                  {tr("Download")}
                </Button>
              ) : (
                <Badge tone={e.status === "failed" ? "bad" : "neutral"}>{tr(STATUS[e.status] ?? e.status)}</Badge>
              )}
            </Row>
          ))}
        </Rows>
      </Section>

      <Section title={tr("Delete your data")}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Ask this organization to erase what you wrote here: room messages, time descriptions and your private AI conversations, with their search index. Records the organization must keep, like commission and audit history, stay. Your access ends when it's done.")}
        </p>
        {pendingRequest ? (
          <Notice>{tr("Your request from {date} is waiting for an admin.", { date: when(pendingRequest.created_at) })}</Notice>
        ) : confirming ? (
          <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
            <label className="mb-3 block text-sm">
              <span className="mb-1 block font-medium">{tr("Anything the admin should know (optional)")}</span>
              <textarea className="v2-input min-h-20" maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="flex gap-2">
              <Button variant="danger" onClick={requestDeletion}>
                {tr("Send deletion request")}
              </Button>
              <Button variant="outline" onClick={() => setConfirming(false)}>
                {tr("Cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="outline" onClick={() => setConfirming(true)}>
            {tr("Request deletion")}
          </Button>
        )}
        {rowsOf<DeletionRequest>(requests.data)
          .filter((r) => r.status !== "pending")
          .map((r) => (
            <p key={r.id} className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
              {r.status === "done"
                ? tr("Request from {date}: completed {decided}.", { date: when(r.created_at), decided: when(r.decided_at) })
                : tr("Request from {date}: rejected {decided}.", { date: when(r.created_at), decided: when(r.decided_at) })}
            </p>
          ))}
      </Section>
    </div>
  );
}
