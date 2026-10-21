/** Content Studio API calls the screens share. */

import { api } from "@/lib/v2/api";
import { apiClient } from "@/lib/axios";

import { mediaUrl, type Asset, type Edl, type Op } from "./model";

const KINDS: Record<string, Asset["kind"]> = { video: "video", audio: "audio", image: "image" };

/** Read duration and size in the browser, so the server can check the length cap. */
function probe(file: File, kind: Asset["kind"]): Promise<{ duration_seconds?: number; width?: number; height?: number }> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const done = (value: { duration_seconds?: number; width?: number; height?: number }) => {
      URL.revokeObjectURL(url);
      resolve(value);
    };
    if (kind === "image") {
      const img = new Image();
      img.onload = () => done({ width: img.naturalWidth, height: img.naturalHeight });
      img.onerror = () => done({});
      img.src = url;
      return;
    }
    const el = document.createElement(kind === "audio" ? "audio" : "video");
    el.preload = "metadata";
    el.onloadedmetadata = () => {
      const video = el as HTMLVideoElement;
      done({
        duration_seconds: Number.isFinite(el.duration) ? Math.round(el.duration * 100) / 100 : undefined,
        width: kind === "video" ? video.videoWidth || undefined : undefined,
        height: kind === "video" ? video.videoHeight || undefined : undefined,
      });
    };
    el.onerror = () => done({});
    el.src = url;
  });
}

/** Presign, PUT the bytes straight to storage, then complete. Returns the ready asset. */
export async function uploadAsset(orgId: string, file: File, onStep?: (step: "upload" | "finish") => void): Promise<Asset> {
  const kind = KINDS[file.type.split("/")[0]];
  if (!kind) throw new Error("unsupported");
  const meta = await probe(file, kind);
  const made = await api.post<Asset>(`/orgs/${orgId}/content/assets`, {
    kind,
    content_type: file.type,
    size_bytes: file.size,
    name: file.name,
  });
  onStep?.("upload");
  // No Authorization header: the URL is the credential (S3 rejects a second one).
  const put = await fetch(mediaUrl(made.upload_url), { method: "PUT", headers: { "Content-Type": file.type }, body: file });
  if (!put.ok) throw new Error(`upload_${put.status}`);
  onStep?.("finish");
  return api.post<Asset>(`/orgs/${orgId}/content/assets/${made.id}/complete`, meta);
}

export function saveEdl(orgId: string, projectId: string, operations: Op[], baseVersion: number, note: string) {
  return api.put<Edl>(`/orgs/${orgId}/content/projects/${projectId}/edl`, { operations, base_version: baseVersion, note });
}

/** Captions are a file download behind the API's auth, so fetch and save it as a blob. */
export async function downloadCaptions(orgId: string, projectId: string, fmt: "srt" | "vtt", asset?: string) {
  const res = await apiClient.get(`/api/v2/orgs/${orgId}/content/projects/${projectId}/captions.${fmt}`, {
    params: asset ? { asset } : undefined,
    responseType: "blob",
  });
  const href = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = `captions.${fmt}`;
  a.click();
  URL.revokeObjectURL(href);
}
