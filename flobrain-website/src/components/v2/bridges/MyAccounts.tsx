"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { myLinkOn, platformName, type BridgeLink, type Overview, type Workspace } from "./logic";

function AccountRow({ orgId, w, link, onChange }: { orgId: string; w: Workspace; link?: BridgeLink; onChange: () => void }) {
  const tr = useTr();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

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

  const name = platformName(w.platform);
  const account = link ? [link.account, link.email].filter(Boolean).join(" · ") : "";
  return (
    <Row className="items-start">
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {name} <span className="text-sm font-normal text-[color:var(--fb-v2-text-muted)]">{w.name}</span>
        </p>
        {account ? (
          <p className="text-sm" dir="auto">
            {account}
          </p>
        ) : null}
        {link?.status === "pending" ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
            {link.found_via === "platform"
              ? tr("This account wrote to FloBrain and uses your email. Is it yours?")
              : tr("We found this account by your email. Is it yours?")}
          </p>
        ) : null}
        {!link ? (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
            {w.platform === "slack"
              ? tr("We look for the Slack account with your FloBrain email. You confirm before anything is linked.")
              : tr("Write any message to FloBrain in Teams first, then come back and confirm here.")}
          </p>
        ) : null}
        {link?.status === "active" ? (
          <label className="mt-1 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={link.mirror}
              disabled={busy}
              onChange={(e) => void act(() => api.patch(`/orgs/${orgId}/bridges/links/${link.id}`, { mirror: e.target.checked }), tr("Saved."))}
            />
            {tr("Send my approvals and notices here too")}
          </label>
        ) : null}
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {link?.status === "active" ? <Badge tone="good">{tr("Linked")}</Badge> : null}
        {link?.status === "pending" ? <Badge tone="waiting">{tr("Waiting for you")}</Badge> : null}
        {!link ? (
          <Button disabled={busy} onClick={() => void act(() => api.post(`/orgs/${orgId}/bridges/links`, { workspace: w.id }), tr("Found it. Confirm that this account is yours."))}>
            {w.platform === "slack" ? tr("Link my Slack") : tr("Link my Teams")}
          </Button>
        ) : null}
        {link?.status === "pending" ? (
          <Button variant="waiting" disabled={busy} onClick={() => void act(() => api.post(`/orgs/${orgId}/bridges/links/${link.id}/confirm`), tr("Linked. Ask your buddy from {name} now.", { name }))}>
            {tr("Yes, confirm")}
          </Button>
        ) : null}
        {link ? (
          <Button variant="ghost" disabled={busy} onClick={() => void act(() => api.del(`/orgs/${orgId}/bridges/links/${link.id}`), tr("Unlinked."))}>
            {link.status === "pending" ? tr("Not mine") : tr("Unlink")}
          </Button>
        ) : null}
      </div>
    </Row>
  );
}

/** Every member: link my Slack or Teams account (found by email, confirmed by me), mirroring, unlink. */
export function MyAccounts({ orgId, data, onChange }: { orgId: string; data: Overview; onChange: () => void }) {
  const tr = useTr();
  const live = data.workspaces.filter((w) => w.status === "active");
  return (
    <Section title={tr("Your accounts")}>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Once linked, your buddies answer you in Slack or Teams with your own access, and actions they propose come to your direct messages for approval.")}
      </p>
      {live.length === 0 ? (
        <Notice>{data.can_manage ? tr("Connect Slack or Teams below first.") : tr("An admin connects Slack and Teams. Then you can link your account here.")}</Notice>
      ) : (
        <Rows>
          {live.map((w) => (
            <AccountRow key={w.id} orgId={orgId} w={w} link={myLinkOn(data.my_links, w.id)} onChange={onChange} />
          ))}
        </Rows>
      )}
    </Section>
  );
}
