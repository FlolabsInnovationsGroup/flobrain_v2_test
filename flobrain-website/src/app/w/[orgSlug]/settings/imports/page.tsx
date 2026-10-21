"use client";

import { useCallback, useEffect, useState } from "react";

import { DocumentPicker } from "@/components/v2/imports/DocumentPicker";
import { History } from "@/components/v2/imports/History";
import { countLines, errorParts, isActive, SOURCE_LABEL } from "@/components/v2/imports/logic";
import { RunPanel } from "@/components/v2/imports/RunPanel";
import { SlackMapping } from "@/components/v2/imports/SlackMapping";
import { SourceCards, SourcePanel, type SourceKey } from "@/components/v2/imports/SourcePanel";
import type { Meta, Run } from "@/components/v2/imports/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

const POLL_MS = 2000;

export default function ImportsPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const on = flag(access, "imports");
  const allowed = has(access, "imports.run");
  const ready = on && allowed;
  const meta = useOrgData<Meta>(orgId, ready ? "/imports/meta" : null);
  const history = useOrgData<{ results: Run[] }>(orgId, ready ? "/imports" : null);
  const [source, setSource] = useState<SourceKey | null>(null);
  const [picked, setCurrent] = useState<Run | null>(null);
  const [adoptActive, setAdoptActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const reloadHistory = history.reload;

  // Pick up an import that is already running (another tab, another admin) until the person moves on.
  const current = picked ?? (adoptActive ? (meta.data?.active ?? null) : null);

  const load = useCallback(
    async (id: string) => {
      if (!orgId) return;
      try {
        const run = await api.get<Run>(`/orgs/${orgId}/imports/${id}`);
        setCurrent(run);
        if (!isActive(run)) reloadHistory();
      } catch (err) {
        setMessage({ kind: "error", text: errorText(err) });
      }
    },
    [orgId, reloadHistory],
  );

  // Live progress while something runs; the history refreshes when it ends.
  const currentId = current?.id;
  const running = isActive(current);
  useEffect(() => {
    if (!currentId || !running) return;
    const timer = setInterval(() => load(currentId), POLL_MS);
    return () => clearInterval(timer);
  }, [currentId, running, load]);

  async function act(fn: () => Promise<Run | void>, ok?: string) {
    setBusy(true);
    setMessage(null);
    try {
      const run = await fn();
      if (run) setCurrent(run);
      if (ok) setMessage({ kind: "ok", text: ok });
      reloadHistory();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  const base = `/orgs/${orgId}/imports`;
  const start = (mapping: unknown) => current && act(() => api.post<Run>(`${base}/${current.id}/start`, { mapping }));
  const discard = () =>
    current &&
    act(async () => {
      await api.del(`${base}/${current.id}`);
      setCurrent(null);
      setAdoptActive(false);
    });
  const cancel = () => current && act(() => api.post<Run>(`${base}/${current.id}/cancel`));
  const undo = (r: Run) => act(() => api.post<Run>(`${base}/${r.id}/undo`), tr("Undo started. Everything this import added is being removed."));
  const resume = (r: Run) => act(() => api.post<Run>(`${base}/${r.id}/resume`));
  const sample = (s: "slack" | "notion") => act(() => api.post<Run>(`${base}/sample`, { source: s }));

  const state = !access ? "loading" : !on ? "off" : !allowed ? "no-access" : meta.state;
  const m = meta.data;

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Import")}
        intro={tr("Bring your team's history from Slack, Notion and Google Drive. We only read from them, and you can undo any import.")}
      />
      <ScreenBody state={state} error={meta.error} onRetry={meta.reload}>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        {m && orgId ? (
          <>
            {current && current.status === "ready" ? (
              current.source === "slack" ? (
                <SlackMapping key={current.id} run={current} meta={m} busy={busy} onStart={start} onDiscard={discard} />
              ) : (
                <DocumentPicker key={current.id} run={current} meta={m} busy={busy} onStart={start} onDiscard={discard} />
              )
            ) : current && isActive(current) ? (
              <RunPanel run={current} busy={busy} onCancel={cancel} />
            ) : current ? (
              <Result
                run={current}
                onDone={() => {
                  setCurrent(null);
                  setAdoptActive(false);
                }}
              />
            ) : (
              <Section title={tr("Where from?")}>
                <SourceCards value={source} onPick={setSource} />
                {source ? <SourcePanel source={source} orgId={orgId} meta={m} busy={busy} onRun={setCurrent} onSample={sample} /> : null}
              </Section>
            )}
            <Section title={tr("Import history")}>
              <History runs={rowsOf<Run>(history.data)} busy={busy || isActive(current)} onUndo={undo} onResume={resume} onOpen={(r) => load(r.id)} />
            </Section>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}

function Result({ run, onDone }: { run: Run; onDone: () => void }) {
  const tr = useTr();
  const counts = countLines(run.counts);
  const text =
    run.status === "done"
      ? tr("Import finished.")
      : run.status === "undone"
        ? tr("Import undone. What it added is gone.")
        : run.status === "cancelled"
          ? tr("Import stopped. What came in so far stays until you undo it.")
          : tr("Import failed.");
  return (
    <Section title={tr(SOURCE_LABEL[run.source])}>
      <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" role="status">
        <p className={run.status === "failed" ? "text-[color:var(--fb-v2-error)]" : run.status === "done" ? "text-[color:var(--fb-v2-success)]" : ""}>{text}</p>
        {run.error ? <p className="mt-1 text-sm text-[color:var(--fb-v2-error)]">{errorParts(run.error).text}</p> : null}
        {counts.length ? <p className="mt-1 text-sm">{counts.map((c) => tr(c.template, { n: c.n.toLocaleString() })).join(" · ")}</p> : null}
        <div className="mt-3 flex justify-end">
          <Button type="button" variant="outline" onClick={onDone}>
            {tr("Import something else")}
          </Button>
        </div>
      </div>
    </Section>
  );
}
