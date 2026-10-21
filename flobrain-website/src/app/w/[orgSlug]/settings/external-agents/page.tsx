"use client";

import { useState } from "react";

import { ExternalQuote, type External } from "@/components/v2/platform/ExternalQuote";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tool = { name: string; description: string; inputSchema: { properties?: Record<string, { type?: string }>; required?: string[] }; readOnly: boolean };
type Server = {
  id: string;
  name: string;
  url: string;
  host: string;
  demo: boolean;
  allowed: boolean;
  status: "pending" | "connected" | "error";
  last_error: string;
  last_checked_at: string | null;
  tools: Tool[];
  tools_hash: string;
  tools_approved: boolean;
};
type Host = { id: string; host: string; note: string };
type Overview = { servers: Server[]; allowlist: Host[]; installation_hosts: string[]; can_manage_allowlist: boolean; demo_server_url: string | null };
type Call = {
  id: string;
  server: { id: string; name: string };
  tool: string;
  arguments: Record<string, unknown>;
  via: "test" | "buddy";
  status: "proposed" | "executed" | "failed" | "rejected" | "expired";
  error: string;
  created_at: string;
  expires_at: string | null;
  external: External | null;
};

const CALL_STATUS: Record<string, string> = { proposed: "Waiting for you", executed: "Answered", failed: "Failed", rejected: "Rejected", expired: "Expired" };

/** Starting arguments for a tool: its required fields, empty. */
function template(tool?: Tool) {
  const out: Record<string, string> = {};
  for (const key of tool?.inputSchema?.required ?? []) out[key] = "";
  return JSON.stringify(out, null, 2);
}

function TryTool({ orgId, server }: { orgId: string; server: Server }) {
  const tr = useTr();
  const [tool, setTool] = useState(server.tools[0]?.name ?? "");
  const [args, setArgs] = useState(template(server.tools[0]));
  const [result, setResult] = useState<Call | null>(null);
  const [error, setError] = useState("");

  async function run() {
    setError("");
    setResult(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(args || "{}");
    } catch {
      setError(tr("The arguments are not valid JSON."));
      return;
    }
    try {
      setResult(await api.post<Call>(`/orgs/${orgId}/external-agents/${server.id}/test`, { tool, arguments: parsed }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="mt-3 rounded-lg bg-[color:var(--fb-v2-page)] p-3">
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label={tr("Tool")}>
          <select
            className="v2-input"
            value={tool}
            onChange={(e) => {
              setTool(e.target.value);
              setArgs(template(server.tools.find((t) => t.name === e.target.value)));
            }}
          >
            {server.tools.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={tr("Arguments (JSON)")}>
          <textarea className="v2-input font-mono text-xs" rows={4} dir="ltr" value={args} onChange={(e) => setArgs(e.target.value)} />
        </Field>
      </div>
      <Button variant="outline" disabled={!tool} onClick={run}>
        {tr("Run once")}
      </Button>
      {error ? <Notice kind="error">{error}</Notice> : null}
      {result?.external ? <ExternalQuote source={server.name} external={result.external} /> : null}
      {result && !result.external ? <Notice kind="error">{result.error || tr("The call failed.")}</Notice> : null}
    </div>
  );
}

function Servers({ orgId, data, reload, isOwner }: { orgId: string; data: Overview; reload: () => void; isOwner: boolean }) {
  const tr = useTr();
  const [form, setForm] = useState({ name: "", url: "", token: "" });
  const [trying, setTrying] = useState<string | null>(null);
  const [host, setHost] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const base = `/orgs/${orgId}/external-agents`;
  return (
    <>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Section title={tr("Allowlist")}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Only hosts on this list can be connected. The owner keeps it, within the hosts FloBrain has reviewed for this server: {hosts}.", {
            hosts: data.installation_hosts.length ? data.installation_hosts.join(", ") : tr("none yet"),
          })}
        </p>
        {isOwner ? (
          <form
            className="mb-3 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api.post(`${base}/allowlist`, { host }), tr("Host added."));
              setHost("");
            }}
          >
            <Field label={tr("Host")}>
              <input className="v2-input w-72" dir="ltr" required placeholder="mcp.example.com" value={host} onChange={(e) => setHost(e.target.value)} />
            </Field>
            <Button type="submit" className="mb-4">
              {tr("Add host")}
            </Button>
          </form>
        ) : (
          <Notice>{tr("Only the owner can change the allowlist.")}</Notice>
        )}
        {data.allowlist.length ? (
          <Rows>
            {data.allowlist.map((h) => (
              <Row key={h.id}>
                <div>
                  <code>{h.host}</code> {h.note ? <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{h.note}</span> : null}
                </div>
                {isOwner ? (
                  <Button variant="danger" onClick={() => act(() => api.del(`${base}/allowlist/${h.id}`), tr("Host removed. Its servers stopped."))}>
                    {tr("Remove")}
                  </Button>
                ) : null}
              </Row>
            ))}
          </Rows>
        ) : (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No hosts yet.")}</p>
        )}
      </Section>

      <Section title={tr("Connect a server")}>
        <form
          className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.post(base, form), tr("Connected. Its tools were imported."));
            setForm({ name: "", url: "", token: "" });
          }}
        >
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label={tr("Name")}>
              <input className="v2-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label={tr("MCP address")} hint={tr("An https address on an allowlisted host.")}>
              <input className="v2-input" dir="ltr" type="url" required placeholder="https://mcp.example.com/mcp" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </Field>
          </div>
          <Field label={tr("Access token (optional)")} hint={tr("Sent to that server only. Stored encrypted and never shown again.")}>
            <input className="v2-input" type="password" autoComplete="off" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button type="submit">{tr("Connect")}</Button>
            {data.demo_server_url ? (
              <Button type="button" variant="outline" onClick={() => setForm({ name: tr("Partner agent (Demo)"), url: data.demo_server_url ?? "", token: "" })}>
                {tr("Use the demo server")}
              </Button>
            ) : null}
          </div>
        </form>
      </Section>

      <Section title={tr("Servers")}>
        {data.servers.length === 0 ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No external agents yet.")}</p> : null}
        <div className="space-y-3">
          {data.servers.map((s) => (
            <div key={s.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium">
                    {s.name} {s.demo ? <Badge tone="waiting">{tr("Demo")}</Badge> : null}
                  </p>
                  <p className="truncate text-sm text-[color:var(--fb-v2-text-muted)]" dir="ltr">
                    {s.url}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {!s.allowed ? <Badge tone="bad">{tr("Host not allowlisted")}</Badge> : null}
                    {s.status === "error" ? <Badge tone="bad">{tr("Could not reach it")}</Badge> : null}
                    <Badge tone={s.tools_approved ? "good" : "waiting"}>{s.tools_approved ? tr("Tools approved") : tr("Tools wait for the owner")}</Badge>
                    {s.last_checked_at ? <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Checked {date}", { date: when(s.last_checked_at) })}</span> : null}
                  </div>
                  {s.last_error ? <Notice kind="error">{s.last_error}</Notice> : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {isOwner && !s.tools_approved ? (
                    <Button onClick={() => act(() => api.post(`${base}/${s.id}/approve-tools`, { tools_hash: s.tools_hash }), tr("Tools approved."))}>{tr("Approve these tools")}</Button>
                  ) : null}
                  <Button variant="outline" onClick={() => act(() => api.post(`${base}/${s.id}/refresh`), tr("Tools imported again."))}>
                    {tr("Import tools again")}
                  </Button>
                  <Button variant="ghost" disabled={!s.tools_approved || !s.allowed} onClick={() => setTrying(trying === s.id ? null : s.id)}>
                    {trying === s.id ? tr("Close") : tr("Try a tool")}
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      if (window.confirm(tr("Disconnect {name}? Its call history goes with it.", { name: s.name }))) act(() => api.del(`${base}/${s.id}`), tr("Disconnected."));
                    }}
                  >
                    {tr("Disconnect")}
                  </Button>
                </div>
              </div>
              <ul className="mt-3 space-y-1 text-sm">
                {s.tools.map((t) => (
                  <li key={t.name}>
                    <code className="font-medium">{t.name}</code> <span className="text-[color:var(--fb-v2-text-muted)]">{t.description}</span>{" "}
                    {t.readOnly ? <Badge>{tr("Says it only reads")}</Badge> : <Badge tone="waiting">{tr("May change things")}</Badge>}
                  </li>
                ))}
              </ul>
              {trying === s.id ? <TryTool orgId={orgId} server={s} /> : null}
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}

function Calls({ orgId }: { orgId: string }) {
  const tr = useTr();
  const calls = useOrgData<Call[]>(orgId, "/external-agents/calls", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function decide(call: Call, decision: "approve" | "reject") {
    setMessage(null);
    try {
      const done = await api.post<Call>(`/orgs/${orgId}/external-agents/calls/${call.id}/${decision}`);
      setMessage({ kind: "ok", text: decision === "approve" ? (done.status === "executed" ? tr("Sent. The answer is below.") : tr("The call failed.")) : tr("Rejected. Nothing was sent.") });
      calls.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <Section title={tr("Calls from your buddies")}>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("A buddy never calls an external agent by itself. It asks, you approve, and FloBrain sends the call. The answer comes back as quoted data.")}
      </p>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={calls.state} error={calls.error} emptyLabel={tr("No calls yet.")} onRetry={calls.reload}>
        <Rows>
          {rowsOf<Call>(calls.data).map((c) => (
            <Row key={c.id} className="block">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium">
                    {c.server.name}: <code>{c.tool}</code> <Badge tone={c.status === "proposed" ? "waiting" : c.status === "executed" ? "good" : "neutral"}>{tr(CALL_STATUS[c.status] ?? c.status)}</Badge>
                  </p>
                  <p className="break-all text-xs text-[color:var(--fb-v2-text-muted)]" dir="ltr">
                    {JSON.stringify(c.arguments)}
                  </p>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {c.via === "buddy" ? tr("Asked by a buddy") : tr("Run from settings")}. {when(c.created_at)}
                  </p>
                </div>
                {c.status === "proposed" ? (
                  <div className="flex gap-2">
                    <Button onClick={() => decide(c, "approve")}>{tr("Approve and send")}</Button>
                    <Button variant="ghost" onClick={() => decide(c, "reject")}>
                      {tr("Reject")}
                    </Button>
                  </div>
                ) : null}
              </div>
              {c.external ? <ExternalQuote source={c.server.name} external={c.external} /> : null}
              {c.status === "failed" && c.error ? <Notice kind="error">{c.error}</Notice> : null}
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </Section>
  );
}

export default function ExternalAgentsPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const canManage = has(access, "integrations.manage");
  const overview = useOrgData<Overview>(orgId, canManage ? "/external-agents" : null);

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("External agents")}
        intro={tr("Let buddies ask other AI agents and MCP servers for help. What they answer is treated as untrusted data: shown and quoted, never followed as instructions.")}
      />
      {canManage ? (
        <ScreenBody state={overview.state} error={overview.error} onRetry={overview.reload}>
          {overview.data && orgId ? <Servers orgId={orgId} data={overview.data} reload={overview.reload} isOwner={overview.data.can_manage_allowlist} /> : null}
        </ScreenBody>
      ) : null}
      {orgId ? <Calls orgId={orgId} /> : null}
    </div>
  );
}
