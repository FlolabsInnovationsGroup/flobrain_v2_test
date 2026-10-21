"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Received = { id: string; endpoint: string; event: string; body: string; signature: string; signature_valid: boolean; received_at: string };
type Inbox = { url: string; demo: boolean; received: Received[] };

function pretty(body: string) {
  try {
    return JSON.stringify(JSON.parse(body), null, 2);
  } catch {
    return body;
  }
}

/**
 * Demo mode only: FloBrain's built-in receiver. It checks each signature like a real receiver
 * would. Outside demo mode the endpoint answers 404 and this section is not shown.
 */
export function DemoInbox({ orgId, hasInboxHook, onAdded }: { orgId: string; hasInboxHook: boolean; onAdded: (secret: string) => void }) {
  const tr = useTr();
  const { data, state, reload } = useOrgData<Inbox>(orgId, "/webhooks/demo-inbox");
  const [message, setMessage] = useState("");
  if (state !== "ready" || !data?.demo) return null;

  async function add() {
    setMessage("");
    try {
      const made = await api.post<{ secret: string }>(`/orgs/${orgId}/webhooks`, { url: data!.url, events: ["task.created", "task.completed", "member.joined"] });
      onAdded(made.secret);
      reload();
    } catch (err) {
      setMessage(errorText(err));
    }
  }

  return (
    <Section
      title={tr("Demo inbox")}
      aside={
        <Button variant="ghost" onClick={reload}>
          {tr("Refresh")}
        </Button>
      }
    >
      <Notice>{tr("Demo: a receiver built into FloBrain. Nothing leaves the server. It checks each signature with the endpoint's secret, as your own code should.")}</Notice>
      {!hasInboxHook ? (
        <Button className="mb-3" variant="outline" onClick={add}>
          {tr("Send webhooks to the demo inbox")}
        </Button>
      ) : null}
      {message ? <Notice kind="error">{message}</Notice> : null}
      {data.received.length === 0 ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Nothing received yet. Create a task or send a test event.")}</p>
      ) : (
        <ul className="space-y-2">
          {data.received.map((r) => (
            <li key={r.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-medium">{r.event}</code>
                <Badge tone={r.signature_valid ? "good" : "bad"}>{r.signature_valid ? tr("Signature valid") : tr("Signature does not match")}</Badge>
                <span className="text-[color:var(--fb-v2-text-muted)]">{when(r.received_at)}</span>
              </div>
              <p className="mt-1 break-all text-xs text-[color:var(--fb-v2-text-muted)]" dir="ltr">
                FloBrain-Signature: {r.signature}
              </p>
              <pre className="mt-2 overflow-x-auto rounded bg-[color:var(--fb-v2-page)] p-2 text-xs" dir="ltr">
                {pretty(r.body)}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
