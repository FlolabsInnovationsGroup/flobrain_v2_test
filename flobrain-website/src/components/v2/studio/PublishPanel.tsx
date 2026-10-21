"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import {
  ASPECT_FOR,
  PLATFORM_LABEL,
  localToIso,
  type Account,
  type ConsentProblem,
  type PlatformCopy,
  type Project,
  type PublishJob,
  type Render,
} from "./model";
import { ConsentProblems, PublishJobs } from "./PublishJobs";

/** AI copy per platform, then a post that waits for approval. Consent is checked on the chosen render. */
export function PublishPanel({ orgId, project, orgSlug }: { orgId: string | null; project: Project; orgSlug: string }) {
  const tr = useTr();
  const { access } = useAccess();
  const publishing = flag(access, "social_publishing");
  const accounts = useOrgData<Account[]>(orgId, publishing ? "/social-accounts" : null, { list: true });
  const jobs = useOrgData<PublishJob[]>(orgId, publishing ? "/publish-jobs" : null, { list: true });
  const renders = useOrgData<Render[]>(orgId, `/content/projects/${project.id}/render`, { list: true });
  const done = rowsOf<Render>(renders.data).filter((r) => r.status === "succeeded");
  const connected = rowsOf<Account>(accounts.data).filter((a) => a.status === "connected");
  const [form, setForm] = useState({ render: "", account: "", title: project.title, description: "", hashtags: "", when: "" });
  const [copy, setCopy] = useState<PlatformCopy | null>(null);
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<ConsentProblem[] | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const render = form.render || done[0]?.id || "";
  const account = form.account || connected[0]?.id || "";

  useEffect(() => {
    if (!render || !orgId) return;
    let stale = false;
    api
      .get<{ problems: ConsentProblem[] }>(`/orgs/${orgId}/content/renders/${render}/consent`)
      .then((res) => !stale && setProblems(res.problems))
      .catch(() => !stale && setProblems(null));
    return () => {
      stale = true;
    };
  }, [render, orgId]);

  async function writeCopy() {
    setBusy(true);
    setMessage(null);
    try {
      const platforms = project.target_platforms.length ? project.target_platforms : ["youtube"];
      const res = await api.post<{ copy: PlatformCopy }>(`/orgs/${orgId}/content/projects/${project.id}/copy`, { platforms });
      setCopy(res.copy);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  function applyCopy(platform: string) {
    const c = copy?.[platform];
    if (c) setForm({ ...form, title: c.title, description: c.description, hashtags: c.hashtags.join(", ") });
  }

  async function submit() {
    setBusy(true);
    setMessage(null);
    try {
      await api.post<PublishJob>(`/orgs/${orgId}/publish-jobs`, {
        project: project.id,
        render,
        social_account: account,
        title: form.title,
        description: form.description,
        hashtags: form.hashtags.split(/[,\s]+/).map((t) => t.replace(/^#/, "")).filter(Boolean),
        scheduled_at: form.when ? localToIso(form.when) : null,
      });
      setMessage({ kind: "ok", text: tr("Sent for approval. Nothing is posted until someone approves it.") });
      jobs.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  const mine = rowsOf<PublishJob>(jobs.data).filter((j) => j.project === project.id);
  const blocked = !!problems && problems.length > 0;

  return (
    <div>
      <div className="mb-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-sm font-medium">{tr("Copy for each platform")}</p>
          <Button variant="outline" onClick={writeCopy} disabled={busy}>
            {copy ? tr("Write again") : tr("Write copy with AI")}
          </Button>
        </div>
        {copy ? (
          <ul className="space-y-2">
            {Object.entries(copy).map(([platform, c]) => (
              <li key={platform} className="rounded-lg p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{PLATFORM_LABEL[platform] ?? platform}</p>
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => applyCopy(platform)}>
                    {tr("Use this")}
                  </Button>
                </div>
                <p className="font-medium">{c.title}</p>
                <p className="whitespace-pre-line text-[color:var(--fb-v2-text-muted)]">{c.description}</p>
                {c.hashtags.length ? <p className="text-[color:var(--fb-v2-accent)]">{c.hashtags.map((t) => `#${t}`).join(" ")}</p> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {!publishing ? (
        <Notice>{tr("Social publishing is switched off for your organization. An admin can turn it on.")}</Notice>
      ) : done.length === 0 ? (
        <Notice>{tr("Render the video first. Only finished renders can be posted.")}</Notice>
      ) : connected.length === 0 ? (
        <Notice>
          {tr("No social account is connected.")}{" "}
          <Link className="underline" href={`/w/${orgSlug}/studio?tab=accounts`}>
            {tr("Connect one")}
          </Link>
        </Notice>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field label={tr("Video")}>
            <select className="v2-input" value={render} onChange={(e) => setForm({ ...form, render: e.target.value })}>
              {done.map((r) => (
                <option key={r.id} value={r.id}>
                  {ASPECT_FOR[r.preset] ?? tr("Template")} · {new Date(r.finished_at ?? r.queued_at).toLocaleString()}
                  {r.demo ? ` · ${tr("Demo")}` : ""}
                </option>
              ))}
            </select>
          </Field>
          {problems ? <ConsentProblems problems={problems} /> : null}
          <Field label={tr("Account")}>
            <select className="v2-input" value={account} onChange={(e) => setForm({ ...form, account: e.target.value })}>
              {connected.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name} ({PLATFORM_LABEL[a.platform] ?? a.platform})
                </option>
              ))}
            </select>
          </Field>
          <Field label={tr("Title")}>
            <input className="v2-input" required maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label={tr("Description")}>
            <textarea className="v2-input min-h-24" maxLength={5000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label={tr("Hashtags")} hint={tr("Separate with commas or spaces.")}>
            <input className="v2-input" value={form.hashtags} onChange={(e) => setForm({ ...form, hashtags: e.target.value })} />
          </Field>
          <Field label={tr("When")} hint={tr("Leave empty to post right after approval.")}>
            <input className="v2-input" type="datetime-local" value={form.when} onChange={(e) => setForm({ ...form, when: e.target.value })} />
          </Field>
          <Button type="submit" disabled={busy || blocked || !form.title.trim()}>
            {tr("Send for approval")}
          </Button>
          {blocked ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Fix consent first.")}</p> : null}
        </form>
      )}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {publishing ? (
        <div className="mt-5">
          <p className="mb-2 text-sm font-medium">{tr("Posts from this project")}</p>
          <PublishJobs orgId={orgId} jobs={mine} onChange={jobs.reload} emptyLabel={tr("No posts yet.")} />
        </div>
      ) : null}
    </div>
  );
}
