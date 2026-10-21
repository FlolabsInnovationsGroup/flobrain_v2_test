"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { RunHistory } from "@/components/v2/automations/RunHistory";
import { cleanForSave, type Workflow } from "@/components/v2/automations/steps";
import { TemplateGallery } from "@/components/v2/automations/TemplateGallery";
import { runStatusLabel, runTone, type RoomOption, type Run, type Template, type WorkflowRow } from "@/components/v2/automations/types";
import { WorkflowEditor } from "@/components/v2/automations/WorkflowEditor";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Editing = { id?: string; workflow: Workflow; problems: string[]; enable: boolean };
type Brief = { daily_brief: boolean; nudges: boolean; preview: string };
type Hosts = { webhook_hosts: string[]; trusted_hosts: string[] };
type Secret = { workflow: string; secret: string; path: string; signature_header: string; timestamp_header: string };

const EXAMPLES = ["Every Monday at 9 summarise last week's blocked tasks in the launch room", "When a task is blocked notify the lead"];

export default function AutomationsPage() {
  const { orgId, access } = useAccess();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const tr = useTr();
  const list = useOrgData<WorkflowRow[]>(orgId, "/automations");
  const runs = useOrgData<Run[]>(orgId, "/automations/runs");
  const templates = useOrgData<Template[]>(orgId, "/automations/templates");
  const brief = useOrgData<Brief>(orgId, "/automations/me");
  const hosts = useOrgData<Hosts>(orgId, "/automations/settings");
  const roomData = useOrgData<RoomOption[]>(orgId, "/rooms");
  const rooms = rowsOf<RoomOption>(roomData.data).filter((r) => r.kind !== "direct");
  const manager = has(access, "automations.manage");

  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [describe, setDescribe] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [secret, setSecret] = useState<Secret | null>(null);
  const [hostText, setHostText] = useState<{ allowed: string; trusted: string } | null>(null);

  const workflows = rowsOf<WorkflowRow>(list.data);
  const runRows = rowsOf<Run>(runs.data);
  const waiting = runRows.filter((r) => r.status === "waiting_approval");

  function reloadAll() {
    list.reload();
    runs.reload();
    templates.reload();
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      reloadAll();
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
      return false;
    }
  }

  async function draft() {
    setMessage(null);
    setDrafting(true);
    try {
      const result = await api.post<{ draft: Workflow; valid: boolean; problems: string[] }>(`/orgs/${orgId}/automations/draft`, { text: describe });
      setEditing({ workflow: result.draft, problems: result.problems, enable: false });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setDrafting(false);
    }
  }

  async function save() {
    if (!editing) return;
    const body = { ...cleanForSave(editing.workflow), ...(editing.id ? {} : { enabled: editing.enable }) };
    try {
      if (editing.id) await api.patch(`/orgs/${orgId}/automations/${editing.id}`, body);
      else await api.post(`/orgs/${orgId}/automations`, body);
      setEditing(null);
      setDescribe("");
      setMessage({ kind: "ok", text: tr("Workflow saved. It runs with your access.") });
      reloadAll();
    } catch (err) {
      const problems = (err as { response?: { data?: { problems?: unknown } } })?.response?.data?.problems;
      setEditing({ ...editing, problems: Array.isArray(problems) ? problems : [errorText(err)] });
    }
  }

  async function saveHosts() {
    if (!hostText) return;
    const split = (s: string) => s.split(/[\s,]+/).map((h) => h.trim()).filter(Boolean);
    if (await act(() => api.put(`/orgs/${orgId}/automations/settings`, { webhook_hosts: split(hostText.allowed), trusted_hosts: split(hostText.trusted) }), tr("Settings saved."))) {
      setHostText(null);
      hosts.reload();
    }
  }

  async function setBrief(patch: Partial<Brief>) {
    try {
      const next = await api.put<Brief>(`/orgs/${orgId}/automations/me`, patch);
      brief.setData({ ...(brief.data as Brief), ...next });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const editor = editing ? (
    <Section title={editing.id ? tr("Edit workflow") : tr("Review the draft")}>
      <div className="flex flex-col gap-4 rounded-xl border border-[color:var(--fb-v2-border-strong)] p-4">
        <label className="block text-sm">
          <span className="mb-1 block font-medium">{tr("Name")}</span>
          <input
            className="v2-input w-full"
            dir="auto"
            maxLength={120}
            value={editing.workflow.name}
            onChange={(e) => setEditing({ ...editing, workflow: { ...editing.workflow, name: e.target.value } })}
          />
        </label>
        <WorkflowEditor value={editing.workflow} rooms={rooms} readOnly={!manager} onChange={(workflow) => setEditing({ ...editing, workflow })} />
        {editing.problems.length ? (
          <div role="alert" className="rounded-lg border border-[color:var(--fb-v2-error)] p-3 text-sm">
            <p className="font-medium">{tr("Fix these before saving:")}</p>
            <ul className="mt-1 list-disc ps-5">
              {editing.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {manager ? (
          <div className="flex flex-wrap items-center gap-3">
            {!editing.id ? (
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" checked={editing.enable} onChange={(e) => setEditing({ ...editing, enable: e.target.checked })} />
                {tr("Turn it on after saving")}
              </label>
            ) : null}
            <Button onClick={save} disabled={!editing.workflow.name.trim() || !editing.workflow.steps.length}>
              {tr("Save workflow")}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              {tr("Cancel")}
            </Button>
          </div>
        ) : (
          <Notice>{tr("Only people who manage automations can save workflows. Ask an admin.")}</Notice>
        )}
      </div>
    </Section>
  ) : null;

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Automations")}
        intro={tr("Workflows that run on a schedule or when something happens. Anything that leaves FloBrain, like an email, waits for your approval.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {waiting.length ? (
        <p className="mb-4 rounded-lg border border-[color:var(--fb-v2-waiting)] px-4 py-3 text-sm">
          <span className="font-medium text-[color:var(--fb-v2-waiting)]">{tr("{n} run(s) waiting for approval.", { n: waiting.length })}</span>{" "}
          <Link href={`/w/${orgSlug}/approvals`} className="underline">
            {tr("Open approvals")}
          </Link>
        </p>
      ) : null}

      <ScreenBody state={list.state} error={list.error} onRetry={list.reload}>
        <Section title={tr("Describe a workflow")}>
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (describe.trim()) draft();
            }}
          >
            <label htmlFor="describe" className="sr-only">
              {tr("Describe a workflow")}
            </label>
            <textarea
              id="describe"
              className="v2-input min-h-20 w-full"
              dir="auto"
              maxLength={2000}
              placeholder={tr("For example: every Monday at 9 summarise last week's blocked tasks in the launch room")}
              value={describe}
              onChange={(e) => setDescribe(e.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={drafting || !describe.trim()}>
                {drafting ? tr("Drafting…") : tr("Draft it")}
              </Button>
              {EXAMPLES.map((example) => (
                <Button key={example} type="button" variant="ghost" className="text-xs" onClick={() => setDescribe(example)}>
                  {example === EXAMPLES[0] ? tr("Try: weekly blocked tasks") : tr("Try: tell the lead about blocked tasks")}
                </Button>
              ))}
            </div>
            <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("The AI drafts the steps. Nothing is saved until you review it.")}</p>
          </form>
        </Section>

        {editor}

        <Section title={tr("Workflows")}>
          {workflows.length ? (
            <Rows>
              {workflows.map((w) => (
                <Row key={w.id}>
                  <div className="min-w-0 flex-1 basis-64">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{w.name}</p>
                      <Badge tone={w.enabled ? "good" : "neutral"}>{w.enabled ? tr("On") : tr("Off")}</Badge>
                      {w.waiting_runs ? <Badge tone="waiting">{tr("{n} waiting for approval", { n: w.waiting_runs })}</Badge> : null}
                    </div>
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {w.trigger_label}
                      {w.run_as ? ` · ${tr("Runs as {name}", { name: w.run_as.name })}` : ""}
                      {w.next_run_at ? ` · ${tr("Next run {when}", { when: when(w.next_run_at) })}` : ""}
                    </p>
                    {w.last_run ? (
                      <p className="mt-1 flex items-center gap-2 text-xs">
                        {tr("Last run {when}", { when: when(w.last_run.created_at) })}
                        <Badge tone={runTone(w.last_run.status)}>{runStatusLabel(tr, w.last_run.status)}</Badge>
                      </p>
                    ) : (
                      <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Never run")}</p>
                    )}
                    {w.hook ? (
                      <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]" dir="ltr">
                        {w.hook.path} · {w.hook.secret_hint}
                      </p>
                    ) : null}
                    {secret?.workflow === w.id ? (
                      <div className="mt-2 rounded-lg border border-[color:var(--fb-v2-border-strong)] p-3 text-xs">
                        <p className="font-medium">{tr("Copy the signing secret now. It is not shown again.")}</p>
                        <code className="mt-1 block break-all" dir="ltr">
                          {secret.secret}
                        </code>
                        <p className="mt-1 break-all" dir="ltr">
                          POST {secret.path}
                          <br />
                          {secret.timestamp_header}
                          <br />
                          {secret.signature_header}
                        </p>
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {w.enabled || manager ? (
                      <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/automations/${w.id}/run`), tr("Started. See the run below."))}>
                        {tr("Run now")}
                      </Button>
                    ) : null}
                    {manager ? (
                      <>
                        <Button
                          variant="outline"
                          onClick={() => act(() => api.post(`/orgs/${orgId}/automations/${w.id}/enable`, { enabled: !w.enabled }), w.enabled ? tr("Turned off.") : tr("Turned on."))}
                        >
                          {w.enabled ? tr("Turn off") : tr("Turn on")}
                        </Button>
                        <Button variant="ghost" onClick={() => setEditing({ id: w.id, workflow: { name: w.name, description: w.description, trigger: w.trigger, steps: w.steps }, problems: [], enable: w.enabled })}>
                          {tr("Edit")}
                        </Button>
                        {w.trigger.type === "webhook" ? (
                          <Button
                            variant="ghost"
                            onClick={async () => {
                              try {
                                const made = await api.post<Omit<Secret, "workflow">>(`/orgs/${orgId}/automations/${w.id}/hook`);
                                setSecret({ ...made, workflow: w.id });
                                list.reload();
                              } catch (err) {
                                setMessage({ kind: "error", text: errorText(err) });
                              }
                            }}
                          >
                            {w.hook ? tr("New signing secret") : tr("Get signing secret")}
                          </Button>
                        ) : null}
                        <Button
                          variant="danger"
                          onClick={() => {
                            if (window.confirm(tr("Delete this workflow and its run history?"))) act(() => api.del(`/orgs/${orgId}/automations/${w.id}`), tr("Deleted."));
                          }}
                        >
                          {tr("Delete")}
                        </Button>
                      </>
                    ) : null}
                  </div>
                </Row>
              ))}
            </Rows>
          ) : (
            <Notice>{tr("No workflows yet. Describe one above or start from a template.")}</Notice>
          )}
        </Section>

        <Section title={tr("Templates")}>
          <TemplateGallery
            templates={rowsOf<Template>(templates.data)}
            rooms={rooms}
            canManage={manager}
            onInstall={(key, body) => act(() => api.post(`/orgs/${orgId}/automations/templates/${key}/install`, body), body.enabled ? tr("Turned on.") : tr("Added. Review it in the list and turn it on when ready."))}
          />
        </Section>

        <Section title={tr("Run history")}>
          <RunHistory runs={runRows} orgSlug={orgSlug} />
        </Section>

        {brief.data ? (
          <Section title={tr("Your daily brief and nudges")}>
            <div className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm">
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={brief.data.daily_brief} onChange={(e) => setBrief({ daily_brief: e.target.checked })} />
                {tr("Send me a daily brief each morning when my organization has it on")}
              </label>
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={brief.data.nudges} onChange={(e) => setBrief({ nudges: e.target.checked })} />
                {tr("Remind me about my overdue tasks")}
              </label>
              <p className="text-[color:var(--fb-v2-text-muted)]" dir="auto">
                {brief.data.preview ? tr("Today it would say: {text}", { text: brief.data.preview }) : tr("Nothing for you today.")}
              </p>
            </div>
          </Section>
        ) : null}

        {hosts.data ? (
          <Section title={tr("Outgoing webhooks")}>
            <div className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm">
              <p className="text-[color:var(--fb-v2-text-muted)]">
                {tr("Workflows can only call these https hosts. Calls wait for approval unless the host is trusted.")}
              </p>
              {hostText ? (
                <>
                  <label className="block">
                    <span className="mb-1 block font-medium">{tr("Allowed hosts")}</span>
                    <input className="v2-input w-full" dir="ltr" value={hostText.allowed} onChange={(e) => setHostText({ ...hostText, allowed: e.target.value })} />
                  </label>
                  <label className="block">
                    <span className="mb-1 block font-medium">{tr("Trusted hosts (no approval)")}</span>
                    <input className="v2-input w-full" dir="ltr" value={hostText.trusted} onChange={(e) => setHostText({ ...hostText, trusted: e.target.value })} />
                  </label>
                  <div className="flex gap-2">
                    <Button onClick={saveHosts}>{tr("Save")}</Button>
                    <Button variant="ghost" onClick={() => setHostText(null)}>
                      {tr("Cancel")}
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p dir="ltr">{hosts.data.webhook_hosts.length ? hosts.data.webhook_hosts.join(", ") : "—"}</p>
                  <p>
                    {tr("Trusted:")} <span dir="ltr">{hosts.data.trusted_hosts.length ? hosts.data.trusted_hosts.join(", ") : "—"}</span>
                  </p>
                  {manager ? (
                    <div>
                      <Button variant="outline" onClick={() => setHostText({ allowed: hosts.data!.webhook_hosts.join(", "), trusted: hosts.data!.trusted_hosts.join(", ") })}>
                        {tr("Change hosts")}
                      </Button>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </Section>
        ) : null}
      </ScreenBody>
    </div>
  );
}
