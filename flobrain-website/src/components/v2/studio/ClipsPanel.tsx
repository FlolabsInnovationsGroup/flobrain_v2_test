"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { clock, type Clip, type Edl } from "./model";

/** AI clip suggestions (never applied on their own) and auto-edit for silences and fillers. */
export function ClipsPanel({
  orgId,
  projectId,
  assetId,
  hasTranscript,
  clips,
  demo,
  onClips,
  onEdl,
  onSeek,
}: {
  orgId: string | null;
  projectId: string;
  assetId: string | null;
  hasTranscript: boolean;
  clips: Clip[];
  demo: boolean;
  onClips: (clips: Clip[]) => void;
  onEdl: (edl: Edl) => void;
  onSeek: (t: number) => void;
}) {
  const tr = useTr();
  const [busy, setBusy] = useState<"clips" | "edit" | string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const mine = clips.filter((c) => c.asset === assetId);

  async function suggest() {
    setBusy("clips");
    setMessage(null);
    try {
      const res = await api.post<{ clips: Clip[]; rejected: string[] }>(`/orgs/${orgId}/content/projects/${projectId}/suggest-clips`, { asset: assetId });
      onClips([...clips.filter((c) => c.asset !== assetId || c.accepted), ...res.clips]);
      setMessage({
        kind: "ok",
        text: res.rejected.length
          ? tr("{n} clips suggested. {m} were dropped because they did not fit the recording.", { n: res.clips.length, m: res.rejected.length })
          : tr("{n} clips suggested. Nothing changes until you accept one.", { n: res.clips.length }),
      });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  async function autoEdit() {
    setBusy("edit");
    setMessage(null);
    try {
      const res = await api.post<Edl & { rejected: string[] }>(`/orgs/${orgId}/content/projects/${projectId}/auto-edit`, { asset: assetId });
      onEdl(res);
      const cuts = res.operations.filter((o) => o.op === "cut" && "by" in o && o.by === "ai").length;
      setMessage({ kind: "ok", text: tr("Auto-edit made version {v} with {n} cuts. Undo brings the previous version back.", { v: res.version, n: cuts }) });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  async function accept(clip: Clip) {
    setBusy(clip.id);
    setMessage(null);
    try {
      const edl = await api.post<Edl>(`/orgs/${orgId}/content/clips/${clip.id}/accept`, {});
      onEdl(edl);
      onClips(clips.map((c) => (c.id === clip.id ? { ...c, accepted: true } : c)));
      setMessage({ kind: "ok", text: tr("Clip kept as a segment.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  if (!assetId) return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Add a recording first.")}</p>;
  if (!hasTranscript) return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Transcribe the recording first. Clips and auto-edit read the transcript.")}</p>;

  return (
    <div>
      {demo ? <Notice>{tr("Demo: suggestions come from the demo model, not a real AI.")}</Notice> : null}
      <div className="mb-3 flex flex-wrap gap-2">
        <Button onClick={suggest} disabled={!!busy}>
          {busy === "clips" ? tr("Finding clips") : tr("Suggest clips")}
        </Button>
        <Button variant="outline" onClick={autoEdit} disabled={!!busy}>
          {busy === "edit" ? tr("Editing") : tr("Auto-edit silences and fillers")}
        </Button>
      </div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {mine.length ? (
        <ul className="space-y-2">
          {mine.map((c) => (
            <li key={c.id} className="rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium">{c.hook_text}</p>
                <Badge tone={c.score >= 0.75 ? "good" : "neutral"}>{tr("Score {n}", { n: Math.round(c.score * 100) })}</Badge>
              </div>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr("{from} to {to}", { from: clock(c.start), to: clock(c.end) })} · {tr("{n} s", { n: Math.round(c.end - c.start) })}
              </p>
              {c.reason ? <p className="mt-1 text-sm">{c.reason}</p> : null}
              <div className="mt-2 flex gap-2">
                <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => onSeek(c.start)}>
                  {tr("Preview")}
                </Button>
                {c.accepted ? (
                  <Badge tone="good">{tr("Kept")}</Badge>
                ) : (
                  <Button variant="outline" className="px-2 py-1 text-xs" disabled={!!busy} onClick={() => accept(c)}>
                    {tr("Keep this clip")}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No suggestions yet.")}</p>
      )}
    </div>
  );
}
