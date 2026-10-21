"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { cn } from "@/lib/utils";

import { clock, type Asset, type Project } from "./model";
import { PeoplePanel } from "./PeoplePanel";
import { uploadAsset } from "./studioApi";

const ACCEPT = "video/mp4,video/quicktime,video/webm,audio/mpeg,audio/wav,audio/mp4,audio/ogg,image/png,image/jpeg,image/webp";

/** Left column: the project's recordings, upload, add from the library, transcribe and tag people. */
export function AssetsPanel({
  orgId,
  project,
  library,
  selected,
  onSelect,
  onProjectChange,
  onLibraryChange,
  onConsentChange,
}: {
  orgId: string | null;
  project: Project;
  library: Asset[];
  selected: string | null;
  onSelect: (id: string) => void;
  onProjectChange: (p: Project) => void;
  onLibraryChange: () => void;
  onConsentChange: () => void;
}) {
  const tr = useTr();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [adding, setAdding] = useState("");
  const sources = project.source_assets.map((id) => library.find((a) => a.id === id)).filter((a): a is Asset => !!a);
  const addable = library.filter((a) => a.status === "ready" && a.kind !== "image" && !project.source_assets.includes(a.id));

  async function setSources(ids: string[], ok: string) {
    const value = await api.patch<Project>(`/orgs/${orgId}/content/projects/${project.id}`, { source_assets: ids });
    onProjectChange(value);
    setMessage({ kind: "ok", text: ok });
  }

  async function upload(file: File) {
    if (!orgId) return;
    setMessage(null);
    setBusy(tr("Uploading {name}", { name: file.name }));
    try {
      const asset = await uploadAsset(orgId, file, (step) => setBusy(step === "finish" ? tr("Checking the upload") : tr("Uploading {name}", { name: file.name })));
      onLibraryChange();
      if (asset.kind !== "image") {
        await setSources([...project.source_assets, asset.id], tr("Uploaded and added to this project."));
        onSelect(asset.id);
      } else {
        setMessage({ kind: "ok", text: tr("Image uploaded. Use it in a brand kit.") });
      }
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error && err.message === "unsupported" ? tr("This file type is not supported.") : errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  async function transcribe(asset: Asset) {
    setMessage(null);
    setBusy(tr("Transcribing {name}", { name: asset.name }));
    try {
      const res = await api.post<Asset & { demo?: boolean }>(`/orgs/${orgId}/content/assets/${asset.id}/transcribe`, {});
      onLibraryChange();
      setMessage({
        kind: "ok",
        text: res.demo ? tr("Demo transcript added. Sample words, not what the file says.") : tr("Transcription started. Words appear when it finishes."),
      });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-semibold">{tr("Recordings")}</h2>
        <Button variant="outline" onClick={() => input.current?.click()} disabled={!!busy}>
          {tr("Upload")}
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          aria-label={tr("Upload a recording")}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) upload(file);
          }}
        />
      </div>
      {busy ? <Notice>{busy}</Notice> : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {sources.length === 0 ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Upload a recording or add one from your library to start editing.")}</p>
      ) : (
        <ul className="space-y-2">
          {sources.map((a) => (
            <li key={a.id}>
              <div
                className={cn(
                  "rounded-lg p-3 ring-1 ring-inset",
                  selected === a.id ? "ring-[color:var(--fb-v2-accent)]" : "ring-[color:var(--fb-v2-border)]",
                )}
              >
                <button type="button" className="block w-full text-start" onClick={() => onSelect(a.id)} aria-pressed={selected === a.id}>
                  <span className="block truncate font-medium">{a.name}</span>
                  <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {a.kind === "audio" ? tr("Audio") : tr("Video")} · {clock(a.duration_seconds)}
                    {a.width && a.height ? ` · ${a.width}×${a.height}` : ""}
                  </span>
                </button>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {a.transcript_status === "done" || a.has_transcript ? (
                    <Badge tone="good">{tr("Transcript")}</Badge>
                  ) : a.transcript_status === "running" ? (
                    <Badge tone="accent">{tr("Transcribing")}</Badge>
                  ) : (
                    <Button variant="outline" className="px-2 py-1 text-xs" disabled={!!busy} onClick={() => transcribe(a)}>
                      {a.transcript_status === "failed" ? tr("Try transcribing again") : tr("Transcribe")}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    className="px-2 py-1 text-xs"
                    onClick={() =>
                      setSources(
                        project.source_assets.filter((id) => id !== a.id),
                        tr("Removed from this project. The file stays in your library."),
                      ).catch((err) => setMessage({ kind: "error", text: errorText(err) }))
                    }
                  >
                    {tr("Remove from project")}
                  </Button>
                </div>
                {selected === a.id && a.kind === "video" ? <PeoplePanel orgId={orgId} assetId={a.id} onChange={onConsentChange} /> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {addable.length ? (
        <form
          className="mt-4 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!adding) return;
            setSources([...project.source_assets, adding], tr("Added to this project."))
              .then(() => onSelect(adding))
              .catch((err) => setMessage({ kind: "error", text: errorText(err) }));
            setAdding("");
          }}
        >
          <label className="flex-1 text-sm">
            <span className="mb-1 block">{tr("Add from your library")}</span>
            <select className="v2-input" value={adding} onChange={(e) => setAdding(e.target.value)}>
              <option value="">{tr("Choose a recording")}</option>
              {addable.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" variant="outline" disabled={!adding}>
            {tr("Add")}
          </Button>
        </form>
      ) : null}
    </div>
  );
}
