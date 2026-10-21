"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { draftFrom, isPast, policyBody, toggle, toolUsable, type Draft } from "./logic";
import type { HubBuddy, HubServer } from "./types";

type Listing = { servers: HubServer[]; buddies: HubBuddy[] };

/** A switch built on a checkbox: keyboard and screen readers get a real control. */
function Switch({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" role="switch" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span
        aria-hidden
        className="relative inline-block h-5 w-9 shrink-0 rounded-full bg-[color:var(--fb-v2-track)] transition-colors peer-checked:bg-[color:var(--fb-v2-accent)] peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--fb-v2-accent)] after:absolute after:top-0.5 after:size-4 after:rounded-full after:bg-white after:transition-all after:content-[''] after:start-0.5 peer-checked:after:start-[1.125rem]"
      />
      <span>{label}</span>
    </label>
  );
}

function ServerCard({ orgId, server, buddies, onSaved }: { orgId: string; server: HubServer; buddies: HubBuddy[]; onSaved: (server: HubServer) => void }) {
  const tr = useTr();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(server.policy));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const expired = isPast(draft.endDate);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const usable = server.policy.tools.filter((t) => toolUsable(draft, t, expired)).length;

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api.put<HubServer>(`/orgs/${orgId}/mcp/servers/${server.id}/policy`, policyBody(draft));
      setMessage({ kind: "ok", text: tr("Saved. Buddies follow the new rules from their next message.") });
      onSaved(saved);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold">{server.name}</h3>
          <p dir="ltr" className="text-start text-xs text-[color:var(--fb-v2-text-muted)]">
            {server.host}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {expired ? <Badge tone="bad">{tr("Access ended")}</Badge> : <Badge tone="good">{tr("{n} of {total} tools usable", { n: usable, total: server.policy.tools.length })}</Badge>}
          {draft.readOnly ? <Badge>{tr("Read-only")}</Badge> : null}
          {server.demo ? <Badge>{tr("Demo")}</Badge> : null}
          {!server.tools_approved ? <Badge tone="bad">{tr("Tools not approved by the owner")}</Badge> : null}
        </div>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">{tr("Tools")}</legend>
        <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-lg bg-[color:var(--fb-v2-page)]">
          {server.policy.tools.map((tool) => {
            const allowed = draft.rules[tool.name] !== "deny";
            const blockedByMode = allowed && draft.readOnly && !tool.read_only;
            return (
              <li key={tool.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <p dir="ltr" className="text-start font-mono text-sm">
                    {tool.name}
                  </p>
                  {tool.description ? <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tool.description}</p> : null}
                  <p className="text-xs text-[color:var(--fb-v2-text-faint)]">
                    {tool.read_only ? tr("Only reads, says the server") : tr("Can change things")}
                    {blockedByMode ? `. ${tr("Off while read-only is on.")}` : ""}
                  </p>
                </div>
                <Switch
                  checked={allowed}
                  label={allowed ? tr("Allowed") : tr("Turned off")}
                  onChange={(on) => set({ rules: { ...draft.rules, [tool.name]: on ? "allow" : "deny" } })}
                />
              </li>
            );
          })}
        </ul>
      </fieldset>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Switch checked={draft.readOnly} onChange={(v) => set({ readOnly: v })} label={tr("Read-only: only tools that just read")} />
          <label className="text-sm">
            <span className="mb-1 block font-medium">{tr("Access ends on")}</span>
            <span className="flex flex-wrap items-center gap-2">
              <input type="date" className="v2-input w-48" value={draft.endDate} onChange={(e) => set({ endDate: e.target.value })} />
              {draft.endDate ? (
                <Button variant="ghost" onClick={() => set({ endDate: "" })}>
                  {tr("No end date")}
                </Button>
              ) : null}
            </span>
            <span className="mt-1 block text-[color:var(--fb-v2-text-muted)]">
              {expired ? tr("This date has passed, so buddies can't use this server.") : tr("After this day, buddies stop using this server until you extend it.")}
            </span>
          </label>
        </div>
        <fieldset className="text-sm">
          <legend className="mb-1 font-medium">{tr("Which buddies may use it")}</legend>
          <p className="mb-2 text-[color:var(--fb-v2-text-muted)]">
            {draft.buddies.length ? tr("Only the buddies you picked.") : tr("Every buddy, while none is picked.")}
          </p>
          <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
            {buddies.map((b) => (
              <li key={b.id}>
                <label className="inline-flex cursor-pointer items-center gap-2">
                  <input type="checkbox" className="size-4 accent-[color:var(--fb-v2-accent)]" checked={draft.buddies.includes(b.id)} onChange={() => set({ buddies: toggle(draft.buddies, b.id) })} />
                  {b.name}
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={save} disabled={busy}>
          {busy ? tr("Saving…") : tr("Save rules")}
        </Button>
        {server.policy.updated_at ? (
          <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Last changed {date}.", { date: when(server.policy.updated_at) })}</span>
        ) : null}
      </div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
    </li>
  );
}

/** Outside MCP servers: the org's rules for each one (tools, read-only, end date, buddies). */
export function ServerGovernance({ orgId, orgSlug }: { orgId: string; orgSlug: string }) {
  const tr = useTr();
  const { data, state, error, reload, setData } = useOrgData<Listing>(orgId, "/mcp/servers");
  const servers = data?.servers ?? [];
  return (
    <ScreenBody state={state} error={error} onRetry={reload}>
      {servers.length === 0 ? (
        <p className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("No outside MCP servers yet.")}{" "}
          <a className="underline" href={`/w/${orgSlug}/settings/external-agents`}>
            {tr("Connect one in External agents.")}
          </a>
        </p>
      ) : (
        <ul className="flex flex-col gap-4">
          {servers.map((s) => (
            <ServerCard
              key={s.id}
              orgId={orgId}
              server={s}
              buddies={data?.buddies ?? []}
              onSaved={(saved) => setData((d) => (d ? { ...d, servers: d.servers.map((x) => (x.id === saved.id ? saved : x)) } : d))}
            />
          ))}
        </ul>
      )}
    </ScreenBody>
  );
}
