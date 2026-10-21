"use client";

import { useState } from "react";

import { DeliveryLog } from "@/components/v2/platform/DeliveryLog";
import { DemoInbox } from "@/components/v2/platform/DemoInbox";
import { McpTryIt } from "@/components/v2/platform/McpTryIt";
import { Secret } from "@/components/v2/platform/Secret";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Token = { id: string; name: string; org: string; scopes: string[]; last4: string; created_at: string; last_used_at: string | null; expires_at: string | null; revoked: boolean };
type Hook = { id: string; url: string; events: string[]; is_active: boolean; created_at: string; demo_inbox?: boolean };

const SCOPES: [string, string][] = [
  ["tasks:read", "Read tasks"],
  ["tasks:write", "Create and update tasks"],
  ["rooms:read", "Read room messages"],
  ["rooms:write", "Post in rooms (as proposals)"],
  ["time:read", "Read time entries"],
  ["knowledge:read", "Search org knowledge"],
  ["mcp", "Use from an AI assistant (MCP)"],
];
const EVENTS: [string, string][] = [
  ["task.created", "A task is created"],
  ["task.completed", "A task is completed"],
  ["member.joined", "Someone joins"],
  ["meeting.ended", "A meeting ends"],
  ["content.published", "A video is published"],
];

export default function DeveloperPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const tokens = useOrgData<Token[]>(orgId, "/me/tokens", { orgScoped: false, list: true });
  const canHooks = has(access, "webhooks.manage");
  const hooks = useOrgData<Hook[]>(orgId, canHooks ? "/webhooks" : null, { list: true });
  const [tokenForm, setTokenForm] = useState({ name: "", scopes: ["tasks:read"], days: "90" });
  const [hookForm, setHookForm] = useState({ url: "", events: ["task.created"] });
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [tryToken, setTryToken] = useState("");
  const [openHook, setOpenHook] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function act<T>(fn: () => Promise<T>, after: (value: T) => void) {
    setMessage(null);
    try {
      after(await fn());
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const check = (list: string[], key: string, on: boolean) => (on ? [...list, key] : list.filter((x) => x !== key));

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("API and webhooks")}
        intro={tr("Connect other tools. Tokens act as you, with only the permissions you pick; webhooks tell another service when something happens.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {secret ? <Secret label={secret.label} value={secret.value} /> : null}

      <Section title={tr("Your access tokens")}>
        <form
          className="mb-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            act(
              () => api.post<Token & { token: string }>("/me/tokens", { org: orgId, name: tokenForm.name, scopes: tokenForm.scopes, expires_in_days: Number(tokenForm.days) }),
              (made) => {
                setSecret({ label: tr("Token \"{name}\"", { name: made.name }), value: made.token });
                if (made.scopes.includes("mcp")) setTryToken(made.token);
                tokens.reload();
              },
            );
          }}
        >
          <Field label={tr("Name")} hint={tr("Where you'll use it, like 'Zapier' or 'my laptop'.")}>
            <input className="v2-input" required value={tokenForm.name} onChange={(e) => setTokenForm({ ...tokenForm, name: e.target.value })} />
          </Field>
          <fieldset className="mb-4 text-sm">
            <legend className="mb-1 font-medium">{tr("It may")}</legend>
            {SCOPES.map(([key, label]) => (
              <label key={key} className="me-4 inline-flex items-center gap-2">
                <input type="checkbox" checked={tokenForm.scopes.includes(key)} onChange={(e) => setTokenForm({ ...tokenForm, scopes: check(tokenForm.scopes, key, e.target.checked) })} />
                {tr(label)}
              </label>
            ))}
          </fieldset>
          <Field label={tr("Expires after")}>
            <select className="v2-input w-48" value={tokenForm.days} onChange={(e) => setTokenForm({ ...tokenForm, days: e.target.value })}>
              <option value="30">{tr("30 days")}</option>
              <option value="90">{tr("90 days")}</option>
              <option value="365">{tr("1 year")}</option>
            </select>
          </Field>
          <Button type="submit">{tr("Create token")}</Button>
        </form>
        <ScreenBody state={tokens.state} error={tokens.error} emptyLabel={tr("No tokens yet.")} onRetry={tokens.reload}>
          <Rows>
            {rowsOf<Token>(tokens.data)
              .filter((t) => t.org === orgId)
              .map((t) => (
                <Row key={t.id}>
                  <div>
                    <p className="font-medium">
                      {t.name} <span className="text-[color:var(--fb-v2-text-muted)]">…{t.last4}</span>
                    </p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {t.scopes.join(", ")}. {t.last_used_at ? tr("Last used {date}.", { date: when(t.last_used_at) }) : tr("Never used.")}
                      {t.expires_at ? ` ${tr("Expires {date}.", { date: when(t.expires_at) })}` : ""}
                    </p>
                  </div>
                  {t.revoked ? (
                    <Badge>{tr("Revoked")}</Badge>
                  ) : (
                    <Button variant="danger" onClick={() => act(() => api.del(`/me/tokens/${t.id}`), () => tokens.reload())}>
                      {tr("Revoke")}
                    </Button>
                  )}
                </Row>
              ))}
          </Rows>
        </ScreenBody>
      </Section>

      <Section title={tr("Try the MCP server")}>
        <McpTryIt key={tryToken} initialToken={tryToken} />
      </Section>

      {canHooks ? (
        <Section title={tr("Webhooks")}>
          <form
            className="mb-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              act(
                () => api.post<Hook & { secret: string }>(`/orgs/${orgId}/webhooks`, hookForm),
                (made) => {
                  setSecret({ label: tr("Signing secret"), value: made.secret });
                  hooks.reload();
                },
              );
            }}
          >
            <Field label={tr("Send to")} hint={tr("An https address on the public internet.")}>
              <input className="v2-input" type="url" required placeholder="https://example.com/flobrain" value={hookForm.url} onChange={(e) => setHookForm({ ...hookForm, url: e.target.value })} />
            </Field>
            <fieldset className="mb-4 text-sm">
              <legend className="mb-1 font-medium">{tr("When")}</legend>
              {EVENTS.map(([key, label]) => (
                <label key={key} className="me-4 inline-flex items-center gap-2">
                  <input type="checkbox" checked={hookForm.events.includes(key)} onChange={(e) => setHookForm({ ...hookForm, events: check(hookForm.events, key, e.target.checked) })} />
                  {tr(label)}
                </label>
              ))}
            </fieldset>
            <Button type="submit">{tr("Add webhook")}</Button>
          </form>
          <ScreenBody state={hooks.state} error={hooks.error} emptyLabel={tr("No webhooks yet.")} onRetry={hooks.reload}>
            <Rows>
              {rowsOf<Hook>(hooks.data).map((h) => (
                <Row key={h.id} className="block">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">
                        {h.url} {h.demo_inbox ? <Badge tone="waiting">{tr("Demo")}</Badge> : null}
                      </p>
                      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{h.events.join(", ")}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={h.is_active ? "good" : "neutral"}>{h.is_active ? tr("On") : tr("Off")}</Badge>
                      <Button variant="ghost" onClick={() => setOpenHook(openHook === h.id ? null : h.id)} aria-expanded={openHook === h.id}>
                        {openHook === h.id ? tr("Hide deliveries") : tr("Deliveries")}
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          if (window.confirm(tr("Delete this webhook? Its delivery log goes with it."))) act(() => api.del(`/orgs/${orgId}/webhooks/${h.id}`), () => hooks.reload());
                        }}
                      >
                        {tr("Delete")}
                      </Button>
                    </div>
                  </div>
                  {openHook === h.id && orgId ? <DeliveryLog orgId={orgId} hookId={h.id} onChanged={hooks.reload} /> : null}
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </Section>
      ) : null}

      {canHooks && orgId ? (
        <DemoInbox
          orgId={orgId}
          hasInboxHook={rowsOf<Hook>(hooks.data).some((h) => h.demo_inbox)}
          onAdded={(value) => {
            setSecret({ label: tr("Signing secret"), value });
            hooks.reload();
          }}
        />
      ) : null}
    </div>
  );
}
