"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText } from "@/lib/v2/api";

import { publishError, publishStatus } from "./labels";
import { PLATFORM_LABEL, localToIso, type ConsentProblem, type PublishJob } from "./model";

export function ConsentProblems({ problems }: { problems: ConsentProblem[] }) {
  const tr = useTr();
  if (!problems.length) return null;
  return (
    <div role="alert" className="my-2 rounded-lg p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-error)]">
      <p className="font-medium text-[color:var(--fb-v2-error)]">{tr("Publishing is blocked until everyone shown has consented.")}</p>
      <ul className="mt-1 list-disc ps-5">
        {problems.map((p, i) => (
          <li key={i}>
            {p.problem === "untagged_faces"
              ? tr("{asset}: {n} people are not tagged yet.", { asset: p.asset_name, n: p.count ?? 1 })
              : tr("{asset}: {person} has not consented to public posts.", { asset: p.asset_name, person: p.person_name || tr("someone") })}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[color:var(--fb-v2-text-muted)]">{tr("Record their consent, or remove the recording they appear in, then render again.")}</p>
    </div>
  );
}

/** Posts with approve (content.approve), cancel and reschedule. */
export function PublishJobs({ orgId, jobs, onChange, emptyLabel }: { orgId: string | null; jobs: PublishJob[]; onChange: () => void; emptyLabel: string }) {
  const tr = useTr();
  const { access } = useAccess();
  const approver = has(access, "content.approve");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [problems, setProblems] = useState<Record<string, ConsentProblem[]>>({});
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);

  async function approve(job: PublishJob) {
    setMessage(null);
    try {
      const done = await api.post<PublishJob>(`/orgs/${orgId}/publish-jobs/${job.id}/approve`, { hash: job.hash });
      setMessage({
        kind: "ok",
        text: done.status === "published" ? tr("Approved and published.") : done.status === "scheduled" ? tr("Approved. It goes out at the scheduled time.") : tr("Approved."),
      });
      onChange();
    } catch (err) {
      const e = apiError(err);
      if (e.code === "consent_missing") {
        const check = await api.get<{ problems: ConsentProblem[] }>(`/orgs/${orgId}/content/renders/${job.render}/consent`).catch(() => ({ problems: [] }));
        setProblems({ ...problems, [job.id]: check.problems });
        setMessage({ kind: "error", text: tr("Not approved: someone in the video has not consented.") });
      } else if (e.code === "changed") {
        setMessage({ kind: "error", text: tr("The post changed since this page loaded. Review it again.") });
        onChange();
      } else setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function cancel(job: PublishJob) {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/publish-jobs/${job.id}/cancel`);
      setMessage({ kind: "ok", text: tr("Post cancelled.") });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function reschedule(job: PublishJob, value: string) {
    setMessage(null);
    try {
      await api.patch(`/orgs/${orgId}/publish-jobs/${job.id}`, { scheduled_at: value ? localToIso(value) : null });
      setEditing(null);
      setMessage({ kind: "ok", text: tr("Time changed. The post needs approval again.") });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {jobs.length === 0 ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{emptyLabel}</p>
      ) : (
        <Rows>
          {jobs.map((j) => {
            const status = publishStatus(tr, j.status);
            const open = ["awaiting_approval", "approved", "scheduled", "failed"].includes(j.status);
            return (
              <Row key={j.id} className="flex-col items-stretch">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium">{j.title}</p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {PLATFORM_LABEL[j.platform] ?? j.platform} ·{" "}
                      {j.status === "published"
                        ? tr("Published {when}", { when: when(j.scheduled_at ?? j.approved_at) })
                        : j.scheduled_at
                          ? tr("Scheduled {when}", { when: when(j.scheduled_at) })
                          : tr("Goes out right after approval")}
                      {j.hashtags.length ? ` · ${j.hashtags.map((t) => `#${t}`).join(" ")}` : ""}
                    </p>
                    {j.error && j.status !== "published" ? <p className="text-sm text-[color:var(--fb-v2-error)]">{publishError(tr, j.error)}</p> : null}
                    {j.external_url ? (
                      <a className="text-sm text-[color:var(--fb-v2-accent)] underline" href={j.external_url} target="_blank" rel="noreferrer noopener">
                        {j.visibility === "private" ? tr("View the post (private until the app is audited)") : tr("View the post")}
                      </a>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {j.platform === "sandbox" ? <Badge>{tr("Sandbox")}</Badge> : null}
                    <Badge tone={status.tone}>{status.text}</Badge>
                    {j.status === "awaiting_approval" && approver ? (
                      <Button variant="waiting" onClick={() => approve(j)}>
                        {tr("Approve")}
                      </Button>
                    ) : null}
                    {open ? (
                      <Button variant="ghost" onClick={() => setEditing({ id: j.id, value: "" })}>
                        {tr("Change time")}
                      </Button>
                    ) : null}
                    {open ? (
                      <Button variant="danger" onClick={() => cancel(j)}>
                        {tr("Cancel")}
                      </Button>
                    ) : null}
                  </div>
                </div>
                {j.status === "awaiting_approval" && !approver ? (
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Someone with approval rights reviews it before it goes out.")}</p>
                ) : null}
                {problems[j.id] ? <ConsentProblems problems={problems[j.id]} /> : null}
                {editing?.id === j.id ? (
                  <form
                    className="mt-2 flex flex-wrap items-end gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      reschedule(j, editing.value);
                    }}
                  >
                    <label className="text-sm">
                      <span className="mb-1 block">{tr("New time (empty: right after approval)")}</span>
                      <input className="v2-input" type="datetime-local" value={editing.value} onChange={(e) => setEditing({ id: j.id, value: e.target.value })} />
                    </label>
                    <Button type="submit" variant="outline">
                      {tr("Save")}
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => setEditing(null)}>
                      {tr("Close")}
                    </Button>
                  </form>
                ) : null}
              </Row>
            );
          })}
        </Rows>
      )}
    </div>
  );
}
