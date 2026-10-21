"use client";

import { useCallback, useEffect, useState } from "react";

import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import { docsEmpty, type DocRow } from "@/lib/v2/screens/docs";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function DocsScreen({ orgSlug, roomId }: { orgSlug: string; roomId: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [selected, setSelected] = useState<DocRow | null>(null);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .roomDocs(orgId, roomId)
      .then((rows) => {
        const next = rows as DocRow[];
        setDocs(next);
        setSelected((current) => next.find((row) => row.id === current?.id) ?? next[0] ?? null);
        setState(docsEmpty(next) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load docs");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, roomId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  useEffect(() => {
    setDraft(selected?.content_text ?? "");
  }, [selected]);

  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">Docs</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="docs" />
      <ScreenBody state={state} error={error || orgError} emptyLabel="No documents yet" onRetry={load}>
        <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
          <ul className="space-y-1">
            {docs.map((doc) => (
              <li key={doc.id}>
                <button type="button" className="text-start" onClick={() => setSelected(doc)}>
                  {doc.title}
                </button>
              </li>
            ))}
          </ul>
          {selected ? (
            <div>
              <textarea
                className="min-h-48 w-full rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent p-3"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <Button
                className="mt-2"
                type="button"
                onClick={() => {
                  if (!orgId) return;
                  v2Client()
                    .patchDoc(orgId, selected.id, { version: selected.version, content_text: draft })
                    .then(load)
                    .catch((err: { response?: { status?: number } }) => {
                      setError(err.response?.status === 409 ? "Document changed" : "Could not save");
                      setState(screenStateFromHttp(err.response?.status ?? 500));
                    });
                }}
              >
                Save
              </Button>
            </div>
          ) : null}
        </div>
      </ScreenBody>
    </section>
  );
}
