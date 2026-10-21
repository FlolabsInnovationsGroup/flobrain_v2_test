"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Delivery = {
  id: string;
  event: string;
  status: "pending" | "sending" | "delivered" | "failed";
  attempts: number;
  max_attempts: number;
  response_code: number | null;
  error: string;
  created_at: string;
  delivered_at: string | null;
  next_attempt_at: string | null;
  payload: unknown;
};
type HookDetail = { id: string; url: string; is_active: boolean; deliveries: Delivery[] };

const TONE = { delivered: "good", failed: "bad", pending: "waiting", sending: "waiting" } as const;
const LABEL: Record<string, string> = { delivered: "Delivered", failed: "Failed", pending: "Waiting to retry", sending: "Sending" };

/** The last 50 deliveries of one endpoint: attempts, status, response code, and a retry. */
export function DeliveryLog({ orgId, hookId, onChanged }: { orgId: string; hookId: string; onChanged?: () => void }) {
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<HookDetail>(orgId, `/webhooks/${hookId}`);
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      reload();
      onChanged?.();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const base = `/orgs/${orgId}/webhooks/${hookId}`;
  return (
    <div className="mt-3 rounded-lg bg-[color:var(--fb-v2-page)] p-3">
      <div className="mb-2 flex flex-wrap gap-2">
        <Button variant="outline" disabled={!data?.is_active} onClick={() => act(() => api.post(`${base}/test`), tr("Test event sent."))}>
          {tr("Send a test event")}
        </Button>
        {data ? (
          <Button variant="ghost" onClick={() => act(() => api.patch(base, { is_active: !data.is_active }), data.is_active ? tr("Turned off.") : tr("Turned on."))}>
            {data.is_active ? tr("Turn off") : tr("Turn on")}
          </Button>
        ) : null}
        <Button variant="ghost" onClick={reload}>
          {tr("Refresh")}
        </Button>
      </div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data && data.deliveries.length === 0 ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Nothing sent yet.")}</p> : null}
        <ul className="divide-y divide-[color:var(--fb-v2-border)] text-sm">
          {(data?.deliveries ?? []).map((d) => (
            <li key={d.id} className="py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={TONE[d.status] ?? "neutral"}>{LABEL[d.status] ? tr(LABEL[d.status]) : d.status}</Badge>
                  <code>{d.event}</code>
                  <span className="text-[color:var(--fb-v2-text-muted)]">
                    {when(d.created_at)}. {tr("Attempt {n} of {max}.", { n: d.attempts, max: d.max_attempts })}{" "}
                    {d.response_code ? tr("Answered {code}.", { code: d.response_code }) : ""} {d.error && !d.response_code ? d.error : ""}
                    {d.next_attempt_at ? ` ${tr("Next try {date}.", { date: when(d.next_attempt_at) })}` : ""}
                  </span>
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={() => setOpen(open === d.id ? null : d.id)}>
                    {open === d.id ? tr("Hide payload") : tr("Payload")}
                  </Button>
                  {d.status === "failed" || d.status === "pending" ? (
                    <Button variant="outline" onClick={() => act(() => api.post(`${base}/deliveries/${d.id}/retry`), tr("Retrying now."))}>
                      {tr("Retry")}
                    </Button>
                  ) : null}
                </div>
              </div>
              {open === d.id ? (
                <pre className="mt-2 overflow-x-auto rounded bg-[color:var(--fb-v2-surface)] p-2 text-xs" dir="ltr">
                  {JSON.stringify(d.payload, null, 2)}
                </pre>
              ) : null}
            </li>
          ))}
        </ul>
      </ScreenBody>
    </div>
  );
}
