"use client";

import { useEffect, useRef, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { getApiBaseUrl } from "@/lib/axios";
import { useOrgData } from "@/lib/v2/useOrgData";

import { PLATFORM_LABEL, type Account, type PlatformInfo } from "./model";

/** Connect and disconnect social accounts. OAuth returns here with a one-time code that the same person confirms. */
export function SocialAccounts({ orgId, returned }: { orgId: string | null; returned: { result: string; confirm: string } | null }) {
  const tr = useTr();
  const { access } = useAccess();
  const manager = has(access, "social.connect");
  const demo = !!access?.org.demo;
  const accounts = useOrgData<Account[]>(orgId, "/social-accounts", { list: true });
  const platforms = useOrgData<PlatformInfo[]>(orgId, "/social-accounts/platforms", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const confirmed = useRef(false);
  const { reload } = accounts;

  // Back from the provider: finish connecting with the one-time code (once).
  useEffect(() => {
    if (!orgId || !returned || confirmed.current) return;
    confirmed.current = true;
    if (returned.result !== "confirm" || !returned.confirm) {
      window.setTimeout(() => setMessage({ kind: "error", text: tr("Connecting did not finish. Start again.") }), 0);
      return;
    }
    api
      .post<Account>(`/orgs/${orgId}/social-accounts/confirm`, { code: returned.confirm })
      .then((a) => {
        setMessage({ kind: "ok", text: tr("{name} is connected.", { name: a.display_name }) });
        reload();
      })
      .catch((err) => setMessage({ kind: "error", text: errorText(err) }));
  }, [orgId, returned, reload, tr]);

  async function connect(platform: string) {
    setMessage(null);
    try {
      const { authorize_url } = await api.post<{ authorize_url: string }>(`/orgs/${orgId}/social-accounts/${platform}/connect`);
      if (platform === "sandbox") {
        // The sandbox has no consent screen: answer the callback as the provider would.
        const state = new URL(authorize_url).searchParams.get("state") ?? "";
        window.location.assign(`${getApiBaseUrl()}/api/v2/oauth/callback/sandbox?state=${encodeURIComponent(state)}&code=good-code`);
        return;
      }
      window.location.assign(authorize_url);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function disconnect(account: Account) {
    setMessage(null);
    try {
      await api.del(`/orgs/${orgId}/social-accounts/${account.id}`);
      setMessage({ kind: "ok", text: tr("Disconnected. Its stored sign-in was deleted.") });
      accounts.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const rows = rowsOf<Account>(accounts.data);
  const connected = new Set(rows.filter((a) => a.status === "connected").map((a) => a.platform));

  return (
    <div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Section title={tr("Connected accounts")}>
        <ScreenBody state={accounts.state} error={accounts.error} emptyLabel={tr("No account connected yet.")} onRetry={accounts.reload}>
          <Rows>
            {rows.map((a) => (
              <Row key={a.id}>
                <div>
                  <p className="font-medium">{a.display_name}</p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {PLATFORM_LABEL[a.platform] ?? a.platform}
                    {a.private_only ? ` · ${tr("Posts are private until the app passes the platform's review")}` : ""}
                    {a.platform === "sandbox" ? ` · ${tr("Posts go to sandbox.invalid, nowhere public")}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {a.status === "connected" ? <Badge tone="good">{tr("Connected")}</Badge> : <Badge>{tr("Disconnected")}</Badge>}
                  {manager && a.status === "connected" ? (
                    <Button variant="danger" onClick={() => disconnect(a)}>
                      {tr("Disconnect")}
                    </Button>
                  ) : null}
                </div>
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>
      <Section title={tr("Platforms")}>
        <ScreenBody state={platforms.state} error={platforms.error} onRetry={platforms.reload}>
          <Rows>
            {rowsOf<PlatformInfo>(platforms.data).map((p) => (
              <Row key={p.platform}>
                <div>
                  <p className="font-medium">{p.label}</p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {p.configured
                      ? tr("Up to {n} minutes. {ratios}.", { n: Math.round(p.capabilities.max_duration_seconds / 60), ratios: p.capabilities.aspect_ratios.join(", ") })
                      : tr("Not set up. FloBrain needs the company's developer app for this platform.")}
                  </p>
                </div>
                {p.configured && manager ? (
                  <Button variant="outline" onClick={() => connect(p.platform)}>
                    {connected.has(p.platform) ? tr("Connect another") : tr("Connect")}
                  </Button>
                ) : !p.configured ? (
                  <Badge>{tr("Not set up")}</Badge>
                ) : null}
              </Row>
            ))}
          </Rows>
        </ScreenBody>
        {!manager ? <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("An admin connects accounts. You can still send posts for approval.")}</p> : null}
        {demo ? <Notice>{tr("Demo: the Sandbox account is connected for you and never posts anywhere public.")}</Notice> : null}
      </Section>
    </div>
  );
}
