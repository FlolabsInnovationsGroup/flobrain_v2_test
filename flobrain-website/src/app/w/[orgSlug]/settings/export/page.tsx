"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

/** Export states from the API, shown as words. */
const STATUS: Record<Export["status"], string> = { queued: "Queued", running: "Running", succeeded: "Ready", failed: "Failed" };

type Export = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  counts: { rooms?: number; messages?: number; documents?: number; truncated?: boolean };
  size_bytes: number;
  error: string;
  created_at: string;
  expires_at: string | null;
};

export default function ExportPage() {
  const tr = useTr();
  const { orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<Export[]>(orgId, "/exports/memory", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function start() {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/exports/memory`);
      setMessage({ kind: "ok", text: tr("Export started. It appears below when it's ready.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function download(id: string) {
    try {
      const res = await api.get<{ download_url?: string | null }>(`/orgs/${orgId}/exports/memory/${id}`);
      if (res.download_url) window.location.assign(res.download_url);
      else setMessage({ kind: "error", text: tr("This export has expired or isn't ready.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={tr("Export")}
        intro={tr("Download your organization's team and project rooms and their documents as one zip (JSON and Markdown). Direct messages, private groups and AI conversations are never included.")}
        action={<Button onClick={start}>{tr("Export now")}</Button>}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("No exports yet.")} onRetry={reload}>
        <Rows>
          {rowsOf<Export>(data).map((e) => (
            <Row key={e.id}>
              <div>
                <p className="font-medium">{when(e.created_at)}</p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {e.status === "succeeded"
                    ? tr("{rooms} rooms, {messages} messages, {documents} documents. {kb} KB. Available until {date}.", {
                        rooms: e.counts.rooms ?? 0,
                        messages: e.counts.messages ?? 0,
                        documents: e.counts.documents ?? 0,
                        kb: (e.size_bytes / 1024).toFixed(0),
                        date: when(e.expires_at),
                      })
                    : e.error || tr("Working on it.")}
                </p>
              </div>
              {e.status === "succeeded" ? (
                <Button variant="outline" onClick={() => download(e.id)}>
                  {tr("Download")}
                </Button>
              ) : (
                <Badge tone={e.status === "failed" ? "bad" : "neutral"}>{tr(STATUS[e.status] ?? e.status)}</Badge>
              )}
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </div>
  );
}
