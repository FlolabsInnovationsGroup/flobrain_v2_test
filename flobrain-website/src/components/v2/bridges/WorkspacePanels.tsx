"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { isTenantId, jsonBlob, platformName, statusTone, workspaceFor, type MirrorKey, type Overview, type Platform, type Workspace } from "./logic";

type Message = { kind: "ok" | "error"; text: string } | null;

function useStatusText() {
  const tr = useTr();
  return (w: Workspace) =>
    w.status === "active" ? tr("Connected") : w.status === "error" ? tr("Error") : w.status === "disconnected" ? tr("Disconnected") : tr("Not set up");
}

function MirrorToggles({ orgId, w, onChange }: { orgId: string; w: Workspace; onChange: () => void }) {
  const tr = useTr();
  const [error, setError] = useState("");
  const labels: Record<MirrorKey, string> = {
    approvals: tr("Approvals waiting for the person"),
    automations: tr("Automation notices and the daily brief"),
    escalations: tr("Customers who need a person"),
  };
  async function toggle(key: MirrorKey, value: boolean) {
    setError("");
    try {
      await api.patch(`/orgs/${orgId}/bridges/workspaces/${w.id}`, { mirror: { [key]: value } });
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <fieldset className="mt-3">
      <legend className="mb-1 text-sm font-medium">{tr("Also send to people's direct messages")}</legend>
      {(Object.keys(labels) as MirrorKey[]).map((key) => (
        <label key={key} className="flex items-center gap-2 py-1 text-sm">
          <input type="checkbox" checked={!!w.mirror?.[key]} onChange={(e) => void toggle(key, e.target.checked)} />
          {labels[key]}
        </label>
      ))}
      <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Only to linked people, only their own notices, and each person can turn it off.")}</p>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </fieldset>
  );
}

function WorkspaceCard({ orgId, w, data, onChange }: { orgId: string; w: Workspace; data: Overview; onChange: () => void }) {
  const tr = useTr();
  const statusText = useStatusText();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message>(null);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{w.name || platformName(w.platform)}</p>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {platformName(w.platform)}
            {w.last_checked_at ? ` · ${tr("Checked {time}", { time: when(w.last_checked_at) })}` : ""}
          </p>
        </div>
        <span className="flex flex-wrap gap-1">
          {w.demo ? <Badge>{tr("Demo, simulated")}</Badge> : null}
          <Badge tone={statusTone(w.status)}>{statusText(w)}</Badge>
        </span>
      </div>
      <p className="text-sm">
        {tr("{n} people linked.", { n: w.linked_people ?? 0 })}
        {w.pending_people ? ` ${tr("{n} waiting to confirm.", { n: w.pending_people })}` : ""}
      </p>
      {w.secret_hints && Object.keys(w.secret_hints).length ? (
        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
          {tr("Saved bot token:")} <span dir="ltr">{w.secret_hints.bot_token}</span>
        </p>
      ) : null}
      {w.status === "error" && w.last_error ? <p className="text-sm text-[color:var(--fb-v2-error)]">{tr("The last check failed: {error}", { error: w.last_error })}</p> : null}
      <Field label={tr("Who answers by default")} hint={tr("People can still ask a buddy by name, like “Finance Buddy: ...”.")}>
        <select
          className="v2-input w-full"
          value={w.default_buddy ?? ""}
          disabled={busy}
          onChange={(e) => void act(() => api.patch(`/orgs/${orgId}/bridges/workspaces/${w.id}`, { default_buddy: e.target.value || null }), tr("Saved."))}
        >
          <option value="">{tr("Flo picks the right buddy (or the first built-in buddy when Flo is off)")}</option>
          {(data.buddies ?? []).map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </Field>
      <MirrorToggles orgId={orgId} w={w} onChange={onChange} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <div className="mt-auto flex flex-wrap gap-2 pt-2">
        <Button
          variant="outline"
          disabled={busy}
          onClick={() =>
            void act(
              () => api.post(`/orgs/${orgId}/bridges/workspaces/${w.id}/test`),
              w.demo ? tr("Connected (simulated, nothing left FloBrain).") : tr("Checked."),
            )
          }
        >
          {tr("Check connection")}
        </Button>
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm(tr("Disconnect? The bot token is deleted and everyone linked here is unlinked."))) {
              void act(() => api.del(`/orgs/${orgId}/bridges/workspaces/${w.id}`), tr("Disconnected."));
            }
          }}
        >
          {tr("Disconnect")}
        </Button>
      </div>
    </div>
  );
}

function SlackConnect({ orgId, data, onChange }: { orgId: string; data: Overview; onChange: () => void }) {
  const tr = useTr();
  const [message, setMessage] = useState<Message>(null);
  async function install() {
    setMessage(null);
    try {
      const res = await api.post<{ authorize_url?: string; simulated?: boolean }>(`/orgs/${orgId}/bridges/slack/install`);
      if (res.authorize_url) {
        window.location.assign(res.authorize_url);
        return;
      }
      setMessage({ kind: "ok", text: tr("Connected in demo mode. Nothing reaches Slack.") });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }
  return (
    <div className="rounded-xl border border-dashed border-[color:var(--fb-v2-border-strong)] p-4">
      <p className="font-semibold">{tr("Slack")}</p>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Install the FloBrain app in your Slack workspace. People mention @FloBrain, write to it directly, or type /flo.")}
      </p>
      {!data.ready.slack ? <Notice>{tr("Slack is not set up on this server yet. See Platform setup.")}</Notice> : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Button disabled={!data.ready.slack} onClick={() => void install()}>
        {tr("Install in Slack")}
      </Button>
    </div>
  );
}

function TeamsConnect({ orgId, data, onChange }: { orgId: string; data: Overview; onChange: () => void }) {
  const tr = useTr();
  const [tenant, setTenant] = useState("");
  const [message, setMessage] = useState<Message>(null);
  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/bridges/teams/connect`, { tenant_id: tenant.trim() });
      setMessage({ kind: "ok", text: data.demo ? tr("Connected in demo mode. Nothing reaches Microsoft.") : tr("Connected. Upload the Teams app next.") });
      setTenant("");
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }
  return (
    <form className="rounded-xl border border-dashed border-[color:var(--fb-v2-border-strong)] p-4" onSubmit={connect}>
      <p className="font-semibold">{tr("Microsoft Teams")}</p>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Connect your Microsoft 365 organization. People mention FloBrain in a channel or chat with it directly.")}
      </p>
      {!data.ready.teams ? <Notice>{tr("Teams is not set up on this server yet. See Platform setup.")}</Notice> : null}
      {data.demo ? null : (
        <Field label={tr("Microsoft 365 tenant ID")} hint={tr("Microsoft Entra admin center, Overview, Tenant ID.")}>
          <input className="v2-input w-full" dir="ltr" autoComplete="off" value={tenant} onChange={(e) => setTenant(e.target.value)} />
        </Field>
      )}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Button type="submit" disabled={!data.ready.teams || (!data.demo && !isTenantId(tenant))}>
        {tr("Connect Teams")}
      </Button>
    </form>
  );
}

function ManifestButton({ orgId }: { orgId: string }) {
  const tr = useTr();
  const [error, setError] = useState("");
  async function download() {
    setError("");
    try {
      const manifest = await api.get<unknown>(`/orgs/${orgId}/bridges/teams/manifest`);
      const url = URL.createObjectURL(jsonBlob(manifest));
      const a = document.createElement("a");
      a.href = url;
      a.download = "manifest.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <div>
      <Button variant="outline" onClick={() => void download()}>
        {tr("Download the Teams app manifest")}
      </Button>
      <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Zip it with two icons (color.png 192 px, outline.png 32 px) and upload it in Teams, Apps, Manage your apps.")}
      </p>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </div>
  );
}

/** Admin: connect Slack and Teams, choose the default buddy, mirroring, check and disconnect. */
export function WorkspacePanels({ orgId, data, onChange }: { orgId: string; data: Overview; onChange: () => void }) {
  const tr = useTr();
  const cards = (["slack", "teams"] as Platform[]).map((p) => ({ p, w: workspaceFor(data.workspaces, p) }));
  return (
    <Section title={tr("Workspaces")}>
      <div className="grid gap-3 md:grid-cols-2">
        {cards.map(({ p, w }) =>
          w ? (
            <div key={p} className="flex flex-col gap-3">
              <WorkspaceCard orgId={orgId} w={w} data={data} onChange={onChange} />
              {p === "teams" ? <ManifestButton orgId={orgId} /> : null}
            </div>
          ) : p === "slack" ? (
            <SlackConnect key={p} orgId={orgId} data={data} onChange={onChange} />
          ) : (
            <div key={p} className="flex flex-col gap-3">
              <TeamsConnect orgId={orgId} data={data} onChange={onChange} />
              {data.ready.teams ? <ManifestButton orgId={orgId} /> : null}
            </div>
          ),
        )}
      </div>
    </Section>
  );
}
