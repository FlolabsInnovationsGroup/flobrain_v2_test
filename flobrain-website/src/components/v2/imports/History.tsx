"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { countLines, errorParts, SOURCE_LABEL, STATUS_LABEL, statusTone } from "./logic";
import type { Run } from "./types";

/** Past imports with what they added, and undo (with a confirmation) or resume. */
export function History({ runs, busy, onUndo, onResume, onOpen }: { runs: Run[]; busy: boolean; onUndo: (r: Run) => void; onResume: (r: Run) => void; onOpen: (r: Run) => void }) {
  const tr = useTr();
  const [confirming, setConfirming] = useState<string | null>(null);
  if (!runs.length) return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No imports yet.")}</p>;
  return (
    <Rows>
      {runs.map((r) => {
        const counts = countLines(r.counts);
        return (
          <Row key={r.id}>
            <div className="min-w-0 flex-1 basis-64">
              <p className="flex flex-wrap items-center gap-2 font-medium">
                <span>{tr(SOURCE_LABEL[r.source])}</span>
                <Badge tone={statusTone(r.status)}>{tr(STATUS_LABEL[r.status])}</Badge>
                {r.is_demo ? <Badge>{tr("Sample")}</Badge> : null}
              </p>
              <p className="truncate text-xs text-[color:var(--fb-v2-text-muted)]">
                {r.label ? `${r.label} · ` : ""}
                {tr("By {name}", { name: r.created_by || tr("Former member") })} · {when(r.created_at)}
              </p>
              {counts.length ? <p className="text-xs">{counts.map((c) => tr(c.template, { n: c.n.toLocaleString() })).join(" · ")}</p> : null}
              {r.error ? <p className="text-xs text-[color:var(--fb-v2-error)]">{errorParts(r.error).text}</p> : null}
              {confirming === r.id ? (
                <div className="mt-2 rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-sm" role="alertdialog" aria-label={tr("Undo this import?")}>
                  <p className="mb-2">{tr("Undo removes every message, document, room and team this import added. Rooms where people have written since are kept, without the imported messages.")}</p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="danger"
                      disabled={busy}
                      onClick={() => {
                        setConfirming(null);
                        onUndo(r);
                      }}
                    >
                      {tr("Undo import")}
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => setConfirming(null)}>
                      {tr("Keep it")}
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              {r.status === "ready" ? (
                <Button type="button" variant="outline" onClick={() => onOpen(r)}>
                  {tr("Continue")}
                </Button>
              ) : null}
              {r.can_resume ? (
                <Button type="button" variant="outline" disabled={busy} onClick={() => onResume(r)}>
                  {tr("Resume")}
                </Button>
              ) : null}
              {r.can_undo && confirming !== r.id ? (
                <Button type="button" variant="ghost" disabled={busy} onClick={() => setConfirming(r.id)}>
                  {tr("Undo")}
                </Button>
              ) : null}
            </div>
          </Row>
        );
      })}
    </Rows>
  );
}
