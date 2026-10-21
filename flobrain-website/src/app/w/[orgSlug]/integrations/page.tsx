"use client";

import { useState } from "react";

import { WriteBackSection } from "@/components/v2/connectors/WriteBackSection";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Connector = {
  key: string;
  name: string;
  description: string;
  auth: string;
  kind: string;
  config_fields: { name: string; label: string; hint: string; optional?: boolean }[];
  token_hint?: string;
  available: boolean;
};
type Connection = {
  id: string;
  connector: string;
  label: string;
  room_name: string;
  room_hidden?: boolean;
  config: Record<string, string | boolean>;
  status: string;
  last_sync_at: string | null;
  last_error: string;
  items: number;
  demo?: boolean;
};
type Item = { id: string; kind: string; external_id: string; title: string; url: string; state: string; connector: string };

export default function IntegrationsPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const manager = has(access, "integrations.manage");
  const demoOrg = !!access?.org.demo;
  const catalog = useOrgData<{ connectors: Connector[]; connections: Connection[] }>(orgId, "/integrations");
  const items = useOrgData<Item[]>(orgId, "/integrations/items");
  const rooms = useOrgData<{ id: string; name: string; kind: string }[]>(orgId, manager ? "/rooms" : null);
  const tasks = useOrgData<{ results: { id: string; title: string }[] }>(orgId, "/tasks");
  const [connecting, setConnecting] = useState<string | null>(null);
  const [form, setForm] = useState<{ room: string; token: string; config: Record<string, string> }>({ room: "", token: "", config: {} });
  const [linkFor, setLinkFor] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      catalog.reload();
      items.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const sharedRooms = rowsOf<{ id: string; name: string; kind: string }>(rooms.data).filter((r) => r.kind === "team" || r.kind === "project");
  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Integrations")}
        intro={tr("Bring work from other tools into FloBrain. What an integration brings in is visible only to the members of the room you connect it to. Disconnecting deletes its access right away.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={catalog.state} error={catalog.error} onRetry={catalog.reload}>
        <Section title={tr("Connected")}>
          {catalog.data?.connections.length ? (
            <Rows>
              {catalog.data.connections.map((c) => (
                <Row key={c.id}>
                  <div>
                    <p className="flex flex-wrap items-center gap-2 font-medium">
                      {c.label}
                      {c.config.repo ? <span className="text-[color:var(--fb-v2-text-muted)]">{String(c.config.repo)}</span> : null}
                      {c.config.database_title ? <span className="text-[color:var(--fb-v2-text-muted)]">{String(c.config.database_title)}</span> : null}
                      {c.demo ? <Badge tone="waiting">{tr("Demo")}</Badge> : null}
                    </p>
                    {c.config.audience_property ? (
                      <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Masterclasses are filtered by the {property} property.", { property: String(c.config.audience_property) })}</p>
                    ) : null}
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("Visible in {room}. {n} items.", { room: c.room_hidden ? tr("a room you're not in") : c.room_name, n: c.items })}{" "}
                      {c.last_sync_at ? tr("Synced {when}.", { when: when(c.last_sync_at) }) : tr("Not synced yet.")}
                      {c.last_error ? ` ${tr("Last error: {error}.", { error: c.last_error })}` : ""}
                    </p>
                  </div>
                  {c.status === "active" && manager ? (
                    <div className="flex gap-2">
                      <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/integrations/connections/${c.id}/sync`), tr("Sync started."))}>
                        {tr("Sync now")}
                      </Button>
                      <Button variant="danger" onClick={() => act(() => api.del(`/orgs/${orgId}/integrations/connections/${c.id}`), tr("Disconnected. Its token was deleted and syncing stopped."))}>
                        {tr("Disconnect")}
                      </Button>
                    </div>
                  ) : (
                    <Badge>{tr(c.status)}</Badge>
                  )}
                </Row>
              ))}
            </Rows>
          ) : (
            <Notice>{tr("Nothing connected yet.")}</Notice>
          )}
        </Section>
        <Section title={tr("Available")}>
          <ul className="grid gap-3 md:grid-cols-2">
            {(catalog.data?.connectors ?? []).map((c) => (
              <li key={c.key} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold">{c.name}</p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{c.description}</p>
                  </div>
                  {c.available ? null : <Badge>{tr("Not set up yet")}</Badge>}
                </div>
                {c.available && manager ? (
                  connecting === c.key ? (
                    <form
                      className="mt-3"
                      onSubmit={(e) => {
                        e.preventDefault();
                        act(() => api.post(`/orgs/${orgId}/integrations/${c.key}/connect`, form), tr("{name} connected. The first sync is running.", { name: c.name })).then(() => setConnecting(null));
                      }}
                    >
                      <Field label={tr("Show what it brings in to")} hint={tr("Only this room's members will see it.")}>
                        <select className="v2-input" required value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })}>
                          <option value="">{tr("Choose a room")}</option>
                          {sharedRooms.map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.name}
                            </option>
                          ))}
                        </select>
                      </Field>
                      {c.config_fields.map((f) => (
                        <Field key={f.name} label={f.label} hint={f.hint}>
                          <input className="v2-input" required={!f.optional} value={form.config[f.name] ?? ""} onChange={(e) => setForm({ ...form, config: { ...form.config, [f.name]: e.target.value } })} />
                        </Field>
                      ))}
                      {demoOrg ? (
                        <Notice>{tr("Demo workspace: no token is needed. The connection brings in sample items and never contacts the real service.")}</Notice>
                      ) : (
                        <Field label={tr("Access token")} hint={c.token_hint || tr("Read-only access is enough. It is stored encrypted and never shown again.")}>
                          <input className="v2-input" type="password" required value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} />
                        </Field>
                      )}
                      <Button type="submit">{tr("Connect")}</Button>
                    </form>
                  ) : (
                    <Button
                      className="mt-3"
                      variant="outline"
                      onClick={() => {
                        setConnecting(c.key);
                        setForm({ room: "", token: "", config: {} });
                      }}
                    >
                      {tr("Connect")}
                    </Button>
                  )
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
        <Section title={tr("Brought in")}>
          <ScreenBody state={items.state} error={items.error} emptyLabel={tr("Nothing yet.")} onRetry={items.reload}>
            <Rows>
              {rowsOf<Item>(items.data).map((i) => (
                <Row key={i.id}>
                  <div className="min-w-0">
                    {i.url ? (
                      <a className="font-medium hover:underline" href={i.url} target="_blank" rel="noreferrer noopener">
                        {i.connector === "github" ? `#${i.external_id} ` : ""}
                        {i.title}
                      </a>
                    ) : (
                      <span className="font-medium">
                        {i.connector === "github" ? `#${i.external_id} ` : ""}
                        {i.title}
                      </span>
                    )}
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {tr("{kind} in {connector}", { kind: tr(i.kind.replace("_", " ")), connector: i.connector })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={i.state === "open" ? "accent" : i.state === "merged" ? "good" : "neutral"}>{tr(i.state)}</Badge>
                    <select className="v2-input w-44 py-1 text-sm" aria-label={tr("Link #{id} to a task", { id: i.external_id })} value={linkFor[i.id] ?? ""} onChange={(e) => setLinkFor({ ...linkFor, [i.id]: e.target.value })}>
                      <option value="">{tr("Link to a task…")}</option>
                      {rowsOf<{ id: string; title: string }>(tasks.data).map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title}
                        </option>
                      ))}
                    </select>
                    <Button variant="ghost" disabled={!linkFor[i.id]} onClick={() => act(() => api.post(`/orgs/${orgId}/tasks/${linkFor[i.id]}/links`, { item: i.id }), tr("Linked."))}>
                      {tr("Link")}
                    </Button>
                  </div>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </Section>
      </ScreenBody>
      {flag(access, "write_integrations") ? <WriteBackSection orgId={orgId} slug={access?.org.slug ?? ""} /> : null}
    </div>
  );
}
