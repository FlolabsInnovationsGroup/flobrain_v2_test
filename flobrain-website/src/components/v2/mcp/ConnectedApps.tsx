"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import type { Grant } from "./types";

/** Apps connected to FloBrain through OAuth: who connected them, what they may do, and disconnect. */
export function ConnectedApps({ orgId, manager }: { orgId: string; manager: boolean }) {
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<{ results: Grant[] }>(orgId, "/mcp/clients", { list: true });
  const [confirming, setConfirming] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const rows = rowsOf<Grant>(data);

  async function revoke(grant: Grant) {
    setMessage(null);
    try {
      await api.del(`/orgs/${orgId}/mcp/clients/${grant.id}`);
      setMessage({ kind: "ok", text: tr("{app} is disconnected. Its access stopped right away.", { app: grant.client.name }) });
      setConfirming(null);
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload} emptyLabel={tr("No apps are connected yet. Add your MCP endpoint to Claude or ChatGPT to connect one.")}>
        <Rows>
          {rows.map((g) => (
            <Row key={g.id} className="items-start">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 font-semibold">
                  {g.client.name}
                  <Badge tone="good">{tr("Connected")}</Badge>
                  {g.client.verified ? <Badge>{tr("Demo")}</Badge> : null}
                </p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  {manager ? `${g.mine ? tr("Connected by you") : tr("Connected by {name}", { name: g.user.name })}. ` : null}
                  {tr("Since {date}.", { date: when(g.created_at) })}{" "}
                  {g.last_used_at ? tr("Last used {date}.", { date: when(g.last_used_at) }) : tr("Not used yet.")}
                </p>
                <ul className="mt-2 flex flex-wrap gap-1" aria-label={tr("What it may do")}>
                  {g.scopes
                    .filter((s) => s.key !== "mcp")
                    .map((s) => (
                      <li key={s.key} className="rounded-full bg-[color:var(--fb-v2-accent-soft)] px-2 py-0.5 text-xs">
                        {tr(s.label)}
                      </li>
                    ))}
                </ul>
              </div>
              {confirming === g.id ? (
                <div className="flex flex-wrap gap-2">
                  <Button variant="danger" onClick={() => revoke(g)}>
                    {tr("Disconnect now")}
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirming(null)}>
                    {tr("Cancel")}
                  </Button>
                </div>
              ) : (
                <Button variant="outline" onClick={() => setConfirming(g.id)} aria-label={tr("Disconnect {app}", { app: g.client.name })}>
                  {tr("Disconnect")}
                </Button>
              )}
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </>
  );
}
