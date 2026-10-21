"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Avatar, Badge, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { platformName, statusTone, type BridgeLink } from "./logic";

/** Admin: who is linked where, with unlink. */
export function LinkedPeople({ orgId, version }: { orgId: string; version: number }) {
  const tr = useTr();
  const { data, reload } = useOrgData<BridgeLink[]>(orgId, `/bridges/links?scope=all&v=${version}`);
  const rows = rowsOf<BridgeLink>(data);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function unlink(link: BridgeLink) {
    if (!window.confirm(tr("Unlink {name}? Their messages from {platform} stop reaching FloBrain.", { name: link.person?.name ?? "", platform: platformName(link.platform) }))) return;
    setMessage(null);
    try {
      await api.del(`/orgs/${orgId}/bridges/links/${link.id}`);
      setMessage({ kind: "ok", text: tr("Unlinked.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <Section title={tr("Linked people")}>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {rows.length === 0 ? (
        <Notice>{tr("Nobody is linked yet.")}</Notice>
      ) : (
        <Rows>
          {rows.map((link) => (
            <Row key={link.id}>
              <span className="flex min-w-0 items-center gap-3">
                <Avatar name={link.person?.name ?? "?"} />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{link.person?.name}</span>
                  <span className="block truncate text-xs text-[color:var(--fb-v2-text-muted)]" dir="auto">
                    {platformName(link.platform)} · {link.account || link.email}
                    {link.confirmed_at ? ` · ${tr("Linked {time}", { time: when(link.confirmed_at) })}` : ""}
                  </span>
                </span>
              </span>
              <span className="flex items-center gap-2">
                <Badge tone={statusTone(link.status)}>{link.status === "active" ? tr("Linked") : tr("Waiting for them to confirm")}</Badge>
                <Button variant="ghost" onClick={() => void unlink(link)}>
                  {tr("Unlink")}
                </Button>
              </span>
            </Row>
          ))}
        </Rows>
      )}
    </Section>
  );
}
