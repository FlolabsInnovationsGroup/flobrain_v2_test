"use client";

import { useEffect, useRef, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { ActionLog } from "./ActionLog";
import { oauthResultText, oauthReturn, withoutOAuthParams, type LogRow, type WriteAction, type WriteCatalog, type WriteConnection, type WriteProvider } from "./connectors";
import { ProviderCard, type OdooForm } from "./ProviderCard";

type Message = { kind: "ok" | "error"; text: string };

/** Write-back connectors on the integrations page: provider cards, action switches and the log. */
export function WriteBackSection({ orgId, slug }: { orgId: string | null; slug: string }) {
  const tr = useTr();
  const catalog = useOrgData<WriteCatalog>(orgId, "/integrations/write");
  const log = useOrgData<LogRow[]>(orgId, "/integrations/write/log");
  const [message, setMessage] = useState<Message | null>(null);
  const [busy, setBusy] = useState(false);
  const handled = useRef(false);
  const { reload: reloadCatalog } = catalog;

  // Back from the provider's sign-in page: finish connecting with the one-time code.
  useEffect(() => {
    if (handled.current || !orgId || typeof window === "undefined") return;
    const back = oauthReturn(window.location.search);
    if (!back) return;
    handled.current = true;
    window.history.replaceState(null, "", withoutOAuthParams(window.location.href));
    const finish =
      back.result === "confirm" && back.code
        ? api.post(`/orgs/${orgId}/integrations/write/confirm`, { code: back.code }).then(() => ({ kind: "ok" as const, text: tr("Connected. Buddies can now propose actions for it.") }))
        : Promise.resolve({ kind: "error" as const, text: tr(oauthResultText(back.result)) });
    finish
      .catch((err) => ({ kind: "error" as const, text: errorText(err) }))
      .then((result) => {
        setMessage(result);
        reloadCatalog();
      });
  }, [orgId, tr, reloadCatalog]);

  async function run(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      catalog.reload();
      log.reload();
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function connect(p: WriteProvider, scope: "org" | "personal") {
    setBusy(true);
    setMessage(null);
    try {
      const res = await api.post<{ authorize_url?: string; simulated?: boolean }>(`/orgs/${orgId}/integrations/write/${p.key}/connect`, { scope });
      if (res.authorize_url && res.authorize_url.startsWith("https://")) {
        window.location.assign(res.authorize_url);
        return;
      }
      setMessage({ kind: "ok", text: res.simulated ? tr("{name} connected as a simulated demo account.", { name: p.name }) : tr("{name} connected.", { name: p.name }) });
      catalog.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  const connectOdoo = (form: OdooForm) =>
    run(() => api.post(`/orgs/${orgId}/integrations/write/odoo/connect`, { ...form, scope: "org" }), tr("{name} connected.", { name: "Odoo" }));
  const disconnect = (c: WriteConnection) =>
    run(() => api.del(`/orgs/${orgId}/integrations/write/connections/${c.id}`), tr("Disconnected. Its tokens were deleted."));
  const toggle = (a: WriteAction, enabled: boolean) =>
    run(
      () => api.patch(`/orgs/${orgId}/integrations/write/actions/${encodeURIComponent(a.tool)}`, { enabled }),
      enabled ? tr("{action} is on.", { action: tr(a.label) }) : tr("{action} is off. Buddies can't propose it.", { action: tr(a.label) }),
    );

  const data = catalog.data;
  return (
    <div className="mt-2 border-t border-[color:var(--fb-v2-border)] pt-6">
      <Section title={tr("Write-back")}>
        <p className="mb-3 max-w-2xl text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Buddies can propose emails, events, issues, contacts, leads and invoice drafts in these apps. Nothing is sent or changed until a person approves it on the approval card.")}
        </p>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        <ScreenBody state={catalog.state} error={catalog.error} onRetry={catalog.reload}>
          {data?.demo ? <Notice>{tr("Demo workspace: every app is connected with a simulated account. Approved actions return example links and never contact the real service.")}</Notice> : null}
          {data && !data.demo && !data.encryption_configured && data.can_manage ? (
            <Notice kind="error">{tr("Encryption is not configured on this server, so apps can't be connected yet.")}</Notice>
          ) : null}
          <ul className="grid gap-3 md:grid-cols-2">
            {(data?.providers ?? []).map((p) => (
              <ProviderCard
                key={p.key}
                provider={p}
                canManage={!!data?.can_manage}
                canAct={!!data?.can_act}
                demo={!!data?.demo}
                busy={busy}
                onConnect={(scope) => connect(p, scope)}
                onConnectOdoo={connectOdoo}
                onDisconnect={disconnect}
                onToggle={toggle}
              />
            ))}
          </ul>
        </ScreenBody>
      </Section>
      <Section title={tr("Recent write actions")}>
        <ScreenBody state={log.state === "empty" ? "ready" : log.state} error={log.error} onRetry={log.reload}>
          <ActionLog rows={rowsOf<LogRow>(log.data)} slug={slug} />
        </ScreenBody>
      </Section>
    </div>
  );
}
