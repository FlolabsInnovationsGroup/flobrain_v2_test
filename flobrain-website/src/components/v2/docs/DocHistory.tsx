"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiError, errorText, rowsOf } from "@/lib/v2/api";
import type { DocRow, Revision } from "@/lib/v2/screens/docs";
import { useOrgData } from "@/lib/v2/useOrgData";

type Shown = { version: number; content_text: string };

/** Revision list with a read-only preview and "Restore this version" (a restore is a new version). */
export function DocHistory({
  orgId,
  doc,
  canRestore,
  blockedReason,
  onRestored,
  onConflict,
  onClose,
}: {
  orgId: string;
  doc: DocRow;
  canRestore: boolean;
  blockedReason?: string;
  onRestored: (doc: DocRow) => void;
  onConflict: (current: DocRow) => void;
  onClose: () => void;
}) {
  const tr = useTr();
  const revisions = useOrgData<Revision[]>(orgId, `/docs/${doc.id}/revisions?v=${doc.version}`, {
    list: true,
  });
  const [shown, setShown] = useState<Shown | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function open(version: number) {
    setMessage(null);
    try {
      setShown(await api.get<Shown>(`/orgs/${orgId}/docs/${doc.id}/revisions/${version}`));
    } catch (err) {
      setMessage(errorText(err));
    }
  }

  async function restore(version: number) {
    setMessage(null);
    try {
      onRestored(
        await api.post<DocRow>(`/orgs/${orgId}/docs/${doc.id}/revisions/${version}/restore`, {
          version: doc.version,
        })
      );
      setShown(null);
    } catch (err) {
      const current = (err as { response?: { data?: { current?: DocRow } } }).response?.data
        ?.current;
      if (apiError(err).status === 409 && current) onConflict(current);
      else setMessage(errorText(err));
    }
  }

  return (
    <section
      aria-label={tr("Version history")}
      className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-semibold">{tr("Version history")}</h3>
        <Button type="button" variant="ghost" onClick={onClose}>
          {tr("Back to the document")}
        </Button>
      </div>
      {message ? <Notice kind="error">{message}</Notice> : null}
      <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
        <ScreenBody
          state={revisions.state}
          error={revisions.error}
          emptyLabel={tr("No earlier versions.")}
          onRetry={revisions.reload}
        >
          <ol className="space-y-1 text-sm">
            {rowsOf<Revision>(revisions.data).map((r) => (
              <li key={r.version}>
                <button
                  type="button"
                  aria-pressed={shown?.version === r.version}
                  onClick={() => void open(r.version)}
                  className={`w-full rounded-lg px-2 py-1.5 text-start hover:bg-[color:var(--fb-v2-border)] ${shown?.version === r.version ? "bg-[color:var(--fb-v2-border)]" : ""}`}
                >
                  <span className="flex items-center gap-2 font-medium">
                    {tr("Version {n}", { n: r.version })}
                    {r.current ? <Badge tone="accent">{tr("Current")}</Badge> : null}
                  </span>
                  <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">
                    {tr("{when} by {name}", {
                      when: when(r.created_at),
                      name: r.created_by?.name ?? tr("someone"),
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </ScreenBody>
        <div className="min-w-0">
          {shown ? (
            <>
              <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-lg p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                {shown.content_text || tr("This version is empty.")}
              </pre>
              {shown.version !== doc.version ? (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button
                    type="button"
                    variant="waiting"
                    disabled={!canRestore}
                    onClick={() => void restore(shown.version)}
                  >
                    {tr("Restore this version")}
                  </Button>
                  <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {canRestore
                      ? tr("Restoring saves it as a new version. Nothing is lost.")
                      : blockedReason}
                  </span>
                </div>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
              {tr("Choose a version to see what it said.")}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
