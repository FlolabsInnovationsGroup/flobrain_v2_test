"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { apiClient } from "@/lib/axios";
import { errorText } from "@/lib/v2/api";

import { acceptedFile, formatBytes } from "./logic";
import { ProgressBar } from "./ProgressBar";
import type { Run, Source } from "./types";

type Props = {
  orgId: string;
  source: Extract<Source, "slack" | "notion_zip" | "files">;
  maxMb: number;
  maxFiles: number;
  hint: string;
  onUploaded: (run: Run) => void;
};

/** Pick or drop the export, then send it with a progress bar. Large files stream to private storage. */
export function UploadBox({ orgId, source, maxMb, maxFiles, hint, onUploaded }: Props) {
  const tr = useTr();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState("");
  const multiple = source === "files";

  function pick(list: FileList | null) {
    setError("");
    const picked = Array.from(list ?? []);
    if (!picked.length) return;
    if (!multiple && picked.length > 1) return setError(tr("Upload one ZIP file."));
    if (picked.length > maxFiles) return setError(tr("Upload at most {n} files at once.", { n: maxFiles }));
    const bad = picked.find((f) => !acceptedFile(source, f.name));
    if (bad) return setError(multiple ? tr("Upload .zip, .docx, .pdf, .txt, .md, .csv or .html files.") : tr("Upload the export as a .zip file."));
    const total = picked.reduce((sum, f) => sum + f.size, 0);
    if (total > maxMb * 1024 * 1024) return setError(tr("Uploads can be at most {n} MB.", { n: maxMb }));
    setFiles(picked);
  }

  async function send() {
    if (!files.length) return;
    setError("");
    setSent(0);
    const body = new FormData();
    body.append("source", source);
    files.forEach((f) => body.append("file", f));
    try {
      const res = await apiClient.post<Run>(`/api/v2/orgs/${orgId}/imports/upload`, body, {
        headers: { "Content-Type": undefined },
        timeout: 0,
        onUploadProgress: (e) => setSent(e.total ? Math.round((e.loaded / e.total) * 100) : null),
      });
      setFiles([]);
      onUploaded(res.data);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSent(null);
    }
  }

  const busy = sent !== null;
  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files);
        }}
        className={`rounded-xl border-2 border-dashed p-5 text-center text-sm ${dragging ? "border-[color:var(--fb-v2-accent)] bg-[color:var(--fb-v2-accent-soft)]" : "border-[color:var(--fb-v2-border-strong)]"}`}
      >
        <p className="mb-3 text-[color:var(--fb-v2-text-muted)]">{hint}</p>
        <input
          ref={input}
          type="file"
          className="sr-only"
          multiple={multiple}
          accept={multiple ? ".zip,.docx,.pdf,.txt,.md,.markdown,.csv,.html,.htm" : ".zip,application/zip"}
          onChange={(e) => pick(e.target.files)}
          aria-label={multiple ? tr("Choose files") : tr("Choose the ZIP file")}
        />
        <Button type="button" variant="outline" onClick={() => input.current?.click()} disabled={busy}>
          {multiple ? tr("Choose files") : tr("Choose the ZIP file")}
        </Button>
        <p className="mt-2 text-xs text-[color:var(--fb-v2-text-faint)]">{tr("Or drop it here. Up to {n} MB.", { n: maxMb })}</p>
      </div>
      {files.length ? (
        <ul className="mt-3 space-y-1 text-sm">
          {files.map((f) => (
            <li key={f.name} className="flex flex-wrap justify-between gap-2">
              <span className="min-w-0 truncate">{f.name}</span>
              <span className="v2-mono text-[color:var(--fb-v2-text-muted)]">{formatBytes(f.size)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {busy ? (
        <div className="mt-3">
          <ProgressBar value={sent} label={tr("Uploading")} />
        </div>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="mt-3 flex justify-end">
        <Button type="button" onClick={send} disabled={!files.length || busy}>
          {busy ? tr("Uploading…") : tr("Upload and check")}
        </Button>
      </div>
    </div>
  );
}
