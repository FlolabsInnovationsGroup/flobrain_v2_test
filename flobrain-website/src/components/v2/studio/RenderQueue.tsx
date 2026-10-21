"use client";

import { useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { renderStatus } from "./labels";
import { ASPECT_FOR, isActive, mediaUrl, type Render } from "./model";

/** Renders with live progress; plays and downloads finished outputs. Polls while anything is queued or running. */
export function RenderQueue({
  orgId,
  path,
  refreshKey = 0,
  showProject = false,
}: {
  orgId: string | null;
  path: string;
  refreshKey?: number;
  showProject?: boolean;
}) {
  const tr = useTr();
  const renders = useOrgData<Render[]>(orgId, `${path}${path.includes("?") ? "&" : "?"}r=${refreshKey}`, { list: true });
  const [playing, setPlaying] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const rows = rowsOf<Render>(renders.data);
  const active = rows.some(isActive);
  const { setData } = renders;

  useEffect(() => {
    if (!active || !orgId) return;
    const timer = window.setInterval(() => {
      api
        .get<Render[]>(`/orgs/${orgId}${path}`)
        .then((value) => setData(value))
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [active, orgId, path, setData]);

  async function cancel(id: string) {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/content/renders/${id}/cancel`);
      renders.reload();
    } catch (err) {
      setMessage(errorText(err));
    }
  }

  return (
    <div>
      {message ? <Notice kind="error">{message}</Notice> : null}
      <ScreenBody state={renders.state} error={renders.error} emptyLabel={tr("No renders yet. Pick a format and press Render.")} onRetry={renders.reload}>
        <Rows>
          {rows.map((r) => {
            const status = renderStatus(tr, r.status);
            const aspect = ASPECT_FOR[r.preset] ?? tr("Template");
            return (
              <Row key={r.id} className="flex-col items-stretch">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium">
                      {showProject && r.project_title ? `${r.project_title} · ` : ""}
                      {aspect}
                      {r.edl_version ? ` · ${tr("edit v{n}", { n: r.edl_version })}` : ""}
                    </p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {r.status === "succeeded" && r.finished_at
                        ? tr("Finished {when}. {n} GPU seconds.", { when: when(r.finished_at), n: r.gpu_seconds.toFixed(1) })
                        : tr("Queued {when}", { when: when(r.queued_at) })}
                      {r.output ? ` · ${r.output.width}×${r.output.height}, ${r.output.duration_seconds.toFixed(1)} s` : ""}
                    </p>
                    {r.error ? <p className="text-sm text-[color:var(--fb-v2-error)]">{r.error}</p> : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {r.demo ? <Badge tone="waiting">{tr("Demo")}</Badge> : null}
                    <Badge tone={status.tone}>{status.text}</Badge>
                    {r.status === "succeeded" && r.output_url ? (
                      <>
                        <Button variant="outline" onClick={() => setPlaying(playing === r.id ? null : r.id)} aria-expanded={playing === r.id}>
                          {playing === r.id ? tr("Hide") : tr("Play")}
                        </Button>
                        <Button variant="ghost" asChild>
                          <a href={mediaUrl(r.output_url)} download target="_blank" rel="noreferrer">
                            {tr("Download")}
                          </a>
                        </Button>
                      </>
                    ) : null}
                    {isActive(r) ? (
                      <Button variant="danger" onClick={() => cancel(r.id)}>
                        {tr("Cancel")}
                      </Button>
                    ) : null}
                  </div>
                </div>
                {isActive(r) ? (
                  <div
                    className="mt-2 h-1.5 overflow-hidden rounded-full bg-[color:var(--fb-v2-border)]"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={r.progress}
                    aria-label={tr("Render progress")}
                  >
                    <div className="h-full bg-[color:var(--fb-v2-accent)] transition-all" style={{ width: `${Math.max(r.progress, 3)}%` }} />
                  </div>
                ) : null}
                {playing === r.id && r.output_url ? (
                  <video
                    className="mt-3 max-h-96 w-auto self-start rounded-lg bg-black"
                    src={mediaUrl(r.output_url)}
                    controls
                    autoPlay
                    playsInline
                  />
                ) : null}
              </Row>
            );
          })}
        </Rows>
      </ScreenBody>
    </div>
  );
}
