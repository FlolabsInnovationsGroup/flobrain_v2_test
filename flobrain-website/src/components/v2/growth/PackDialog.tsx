"use client";

import { Bot, Clock, FileText, Hash, Workflow, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { groupPreview, type PackItem, type PackPreview, type PackSummary } from "./growth";

const ICONS = { room: Hash, doc: FileText, buddy: Bot, automation: Workflow, time_tag: Clock } as const;
export const KIND_LABEL: Record<PackItem["kind"], string> = {
  room: "Room",
  doc: "Knowledge document",
  buddy: "Buddy",
  automation: "Workflow",
  time_tag: "Time tracking",
};
const REASON: Record<string, string> = { changed: "Someone changed it", in_use: "It is in use" };

type Done = { created: { key: string; label: string }[]; skipped: { key: string; label: string; needs: string }[] };
type Removed = { removed: { key: string; label: string }[]; kept: { key: string; label: string; reason: string }[] };

function ItemRow({ item, note }: { item: Pick<PackItem, "kind" | "label" | "detail">; note?: React.ReactNode }) {
  const tr = useTr();
  const Icon = ICONS[item.kind] ?? FileText;
  return (
    <li className="flex items-start gap-3 py-2">
      <Icon size={16} aria-hidden className="mt-0.5 shrink-0 text-[color:var(--fb-v2-text-muted)]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          {tr(item.label)} <span className="font-normal text-[color:var(--fb-v2-text-muted)]">· {tr(KIND_LABEL[item.kind])}</span>
        </p>
        {item.detail ? <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr(item.detail)}</p> : null}
      </div>
      {note}
    </li>
  );
}

/** Preview then install, or confirm then uninstall, one pack. */
export function PackDialog({
  orgId,
  pack,
  mode,
  onClose,
  onDone,
}: {
  orgId: string;
  pack: PackSummary;
  mode: "install" | "uninstall";
  onClose: () => void;
  onDone: () => void;
}) {
  const tr = useTr();
  const [preview, setPreview] = useState<PackPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [installed, setInstalled] = useState<Done | null>(null);
  const [removed, setRemoved] = useState<Removed | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<PackPreview>(`/orgs/${orgId}/packs/${pack.key}/preview`)
      .then((p) => !cancelled && setPreview(p))
      .catch((err) => !cancelled && setError(errorText(err)));
    return () => {
      cancelled = true;
    };
  }, [orgId, pack.key]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "install") setInstalled(await api.post<Done>(`/orgs/${orgId}/packs/${pack.key}/install`, { confirm: true }));
      else setRemoved(await api.post<Removed>(`/orgs/${orgId}/packs/${pack.key}/uninstall`, { confirm: true }));
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const groups = preview ? groupPreview(preview.items) : null;
  const finished = installed || removed;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="pack-dialog-title">
      <div className="flex max-h-[90dvh] w-full max-w-xl flex-col rounded-t-xl bg-[color:var(--fb-v2-surface)] shadow-xl sm:rounded-xl">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--fb-v2-border)] p-4">
          <div className="min-w-0">
            <h2 id="pack-dialog-title" className="text-lg font-semibold">
              {mode === "install" ? tr("Install the {name} pack", { name: tr(pack.name) }) : tr("Uninstall the {name} pack", { name: tr(pack.name) })}
            </h2>
            <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
              {mode === "install"
                ? tr("This is exactly what will be created. Nothing runs or is sent until you switch it on.")
                : tr("Removes what the pack created, unless someone changed it or it is in use. Those stay.")}
            </p>
          </div>
          <button type="button" aria-label={tr("Close")} onClick={onClose} autoFocus className="rounded p-1 hover:bg-[color:var(--fb-v2-border)]">
            <X size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {error ? <Notice kind="error">{error}</Notice> : null}
          {!preview && !error ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Loading")}…</p> : null}
          {installed ? (
            <>
              <Notice kind="ok">
                {installed.created.length ? tr("Installed. {n} things were created.", { n: installed.created.length }) : tr("Already installed. Nothing new to create.")}
              </Notice>
              {installed.skipped.length ? (
                <ul className="divide-y divide-[color:var(--fb-v2-border)]">
                  {installed.skipped.map((s) => (
                    <li key={s.key} className="py-2 text-sm">
                      {tr(s.label)}: {s.needs === "error" ? tr("Could not be created") : tr("Needs {feature}", { feature: tr(s.needs) })}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
          {removed ? (
            <>
              <Notice kind="ok">{tr("Uninstalled. {n} things were removed.", { n: removed.removed.length })}</Notice>
              {removed.kept.length ? (
                <>
                  <p className="mt-2 text-sm font-medium">{tr("Kept")}</p>
                  <ul className="divide-y divide-[color:var(--fb-v2-border)]">
                    {removed.kept.map((k) => (
                      <li key={k.key} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
                        <span>{tr(k.label)}</span>
                        <span className="text-[color:var(--fb-v2-text-muted)]">{tr(REASON[k.reason] ?? k.reason)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </>
          ) : null}
          {groups && !finished ? (
            mode === "install" ? (
              <>
                {groups.create.length ? (
                  <>
                    <p className="text-sm font-medium">{tr("Will be created ({n})", { n: groups.create.length })}</p>
                    <ul className="divide-y divide-[color:var(--fb-v2-border)]">
                      {groups.create.map((i) => (
                        <ItemRow key={i.key} item={i} />
                      ))}
                    </ul>
                  </>
                ) : (
                  <Notice>{tr("Everything this pack can create is already here.")}</Notice>
                )}
                {groups.skip.length ? (
                  <>
                    <p className="mt-4 text-sm font-medium">{tr("Needs another feature ({n})", { n: groups.skip.length })}</p>
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Skipped for now. Install again after the feature is turned on to add them.")}</p>
                    <ul className="divide-y divide-[color:var(--fb-v2-border)]">
                      {groups.skip.map((i) => (
                        <ItemRow key={i.key} item={i} note={<Badge>{tr("Needs {feature}", { feature: tr(i.needs) })}</Badge>} />
                      ))}
                    </ul>
                  </>
                ) : null}
                {groups.installed.length ? (
                  <>
                    <p className="mt-4 text-sm font-medium">{tr("Already installed ({n})", { n: groups.installed.length })}</p>
                    <ul className="divide-y divide-[color:var(--fb-v2-border)]">
                      {groups.installed.map((i) => (
                        <ItemRow key={i.key} item={i} note={i.action === "removed" ? <Badge>{tr("Removed since")}</Badge> : <Badge tone="good">{tr("Installed")}</Badge>} />
                      ))}
                    </ul>
                  </>
                ) : null}
              </>
            ) : (
              <>
                <p className="text-sm font-medium">{tr("Created by this pack ({n})", { n: groups.installed.length })}</p>
                <ul className="divide-y divide-[color:var(--fb-v2-border)]">
                  {groups.installed.map((i) => (
                    <ItemRow key={i.key} item={i} />
                  ))}
                </ul>
              </>
            )
          ) : null}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-[color:var(--fb-v2-border)] p-4">
          {finished ? (
            <Button onClick={onClose}>{tr("Done")}</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onClose}>
                {tr("Cancel")}
              </Button>
              {mode === "install" ? (
                <Button onClick={run} disabled={busy || !preview || !groups?.create.length}>
                  {tr("Install {n} things", { n: groups?.create.length ?? 0 })}
                </Button>
              ) : (
                <Button variant="outline" onClick={run} disabled={busy || !preview}>
                  {tr("Uninstall")}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
