"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiClientUpload, errorText } from "@/lib/v2/api";
import { apiPath, formatBytes, type Attachment } from "@/lib/v2/screens/docs";
import { useOrgData } from "@/lib/v2/useOrgData";
import { apiClient } from "@/lib/axios";

type Files = { storage: string; max_bytes: number; results: Attachment[] };

/** Files attached to one document: upload (presign, upload, complete), download, remove. */
export function DocAttachments({
  orgId,
  docId,
  canWrite,
}: {
  orgId: string;
  docId: string;
  canWrite: boolean;
}) {
  const tr = useTr();
  const files = useOrgData<Files>(orgId, `/docs/${docId}/files`);
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const storageReady = files.data?.storage === "local";

  async function upload(file: File) {
    setMessage(null);
    if (files.data && file.size > files.data.max_bytes) {
      setMessage({
        kind: "error",
        text: tr("{name} is too large. The limit is {size}.", {
          name: file.name,
          size: formatBytes(files.data.max_bytes),
        }),
      });
      return;
    }
    setBusy(tr("Uploading {name}…", { name: file.name }));
    try {
      const slot = await api.post<{ id: string; upload_url: string; field: string }>(
        `/orgs/${orgId}/files/presign`,
        {
          name: file.name,
          content_type: file.type,
          document: docId,
          size: file.size,
        }
      );
      const body = new FormData();
      body.append(slot.field || "file", file);
      await apiClientUpload(apiPath(slot.upload_url), body);
      await api.post(`/orgs/${orgId}/files/${slot.id}/complete`);
      setMessage({ kind: "ok", text: tr("{name} attached.", { name: file.name }) });
      files.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
      if (input.current) input.current.value = "";
    }
  }

  async function download(file: Attachment) {
    if (!file.download_url) return;
    setMessage(null);
    try {
      const res = await apiClient.get<Blob>(file.download_url, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function remove(file: Attachment) {
    setMessage(null);
    try {
      await api.del(`/orgs/${orgId}/files/${file.id}`);
      files.setData(
        files.data
          ? { ...files.data, results: files.data.results.filter((f) => f.id !== file.id) }
          : files.data
      );
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const rows = files.data?.results ?? [];
  return (
    <section aria-labelledby={`files-${docId}`} className="mt-6">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 id={`files-${docId}`} className="text-sm font-semibold">
          {tr("Attachments")}
        </h3>
        {canWrite && storageReady ? (
          <>
            <input
              ref={input}
              type="file"
              className="sr-only"
              aria-label={tr("Attach a file")}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            <Button
              type="button"
              variant="outline"
              disabled={!!busy}
              onClick={() => input.current?.click()}
            >
              {tr("Attach a file")}
            </Button>
          </>
        ) : null}
      </div>
      {busy ? <Notice>{busy}</Notice> : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {files.state === "error" ? (
        <Notice kind="error">{files.error || tr("Could not load attachments.")}</Notice>
      ) : null}
      {files.data && !storageReady && canWrite ? (
        <Notice>
          {tr("Attaching files needs file storage (S3), which isn't set up on this server yet.")}
        </Notice>
      ) : null}
      {rows.length ? (
        <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
          {rows.map((f) => (
            <li
              key={f.id}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <div className="min-w-0">
                <button
                  type="button"
                  className="truncate font-medium hover:underline"
                  onClick={() => void download(f)}
                >
                  {f.name}
                </button>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  {tr("{size}, added {when} by {name}", {
                    size: formatBytes(f.size_bytes),
                    when: when(f.created_at),
                    name: f.created_by?.name ?? tr("someone"),
                  })}
                </p>
              </div>
              {canWrite ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => void remove(f)}
                  aria-label={tr("Remove {name}", { name: f.name })}
                >
                  {tr("Remove")}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : files.state === "ready" && storageReady ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No files attached.")}</p>
      ) : null}
    </section>
  );
}
