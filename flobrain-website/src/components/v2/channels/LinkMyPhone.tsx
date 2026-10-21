"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { KIND_LABEL, type Linkable, type MyLink } from "./logic";

/** Link my WhatsApp or Telegram to my buddy with a one-time code. */
export function LinkMyPhone({ orgId }: { orgId: string }) {
  const tr = useTr();
  const { data, reload } = useOrgData<{ links: MyLink[]; connections: Linkable[] }>(orgId, "/channels/links");
  const [code, setCode] = useState<{ code: string; connection: Linkable; expires_at: string | null } | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const connections = data?.connections ?? [];
  const links = (data?.links ?? []).filter((l) => l.status === "active");

  async function makeCode(c: Linkable) {
    setMessage(null);
    try {
      const res = await api.post<MyLink>(`/orgs/${orgId}/channels/links`, { connection: c.id });
      setCode({ code: res.code ?? "", connection: c, expires_at: res.expires_at });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function unlink(id: string) {
    try {
      await api.del(`/orgs/${orgId}/channels/links/${id}`);
      setMessage({ kind: "ok", text: tr("Unlinked.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <Section title={tr("Talk to your buddy from your phone")}>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Link your WhatsApp or Telegram, then message your buddy there. You can also answer approvals by replying “approve” or “reject” with the short code.")}
      </p>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {links.length ? (
        <Rows>
          {links.map((l) => (
            <Row key={l.id}>
              <span>
                <span className="font-medium">{tr(KIND_LABEL[l.kind])}</span> <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{l.contact}</span>
              </span>
              <span className="flex items-center gap-2">
                <Badge tone="good">{tr("Linked")}</Badge>
                <Button variant="ghost" onClick={() => unlink(l.id)}>
                  {tr("Unlink")}
                </Button>
              </span>
            </Row>
          ))}
        </Rows>
      ) : null}
      {connections.length === 0 ? (
        <Notice>{tr("No WhatsApp or Telegram is connected for your team yet.")}</Notice>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {connections.map((c) => (
            <Button key={c.id} variant="outline" onClick={() => makeCode(c)}>
              {tr("Link my {channel}", { channel: tr(KIND_LABEL[c.kind]) })}
            </Button>
          ))}
        </div>
      )}
      {code ? (
        <div className="mt-4 rounded-xl border border-[color:var(--fb-v2-border-strong)] bg-[color:var(--fb-v2-surface)] p-4" role="status">
          <p className="text-sm">
            {code.connection.contact
              ? tr("Send this code to {contact} on {channel}:", { contact: code.connection.contact, channel: tr(KIND_LABEL[code.connection.kind]) })
              : tr("Send this code to the {channel} bot:", { channel: tr(KIND_LABEL[code.connection.kind]) })}
          </p>
          <p className="my-2 font-[family-name:var(--fb-v2-font-mono)] text-3xl tracking-[0.3em]" dir="ltr">
            {code.code}
          </p>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("It works once and stops working at {time}.", { time: when(code.expires_at) })}
            {code.connection.demo ? ` ${tr("Demo: use Simulate below instead of a real phone.")}` : ""}
          </p>
          <Button className="mt-2" variant="ghost" onClick={() => { setCode(null); reload(); }}>
            {tr("Done")}
          </Button>
        </div>
      ) : null}
    </Section>
  );
}
