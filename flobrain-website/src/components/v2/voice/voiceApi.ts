import { apiClient } from "@/lib/axios";
import { apiClientUpload } from "@/lib/v2/api";

import { uploadFile } from "./recorderState";

export type VoiceNoteRow = {
  id: string;
  message: string;
  room: string;
  author: string | null;
  status: "pending" | "done" | "failed";
  error: string;
  duration: number;
  content_type: string;
  language: string;
  transcript: string;
  demo: boolean;
  audio_url: string;
  created_at: string;
  translated: boolean;
  translation?: string;
  translation_error?: string;
};

export type VoiceInputResult = { text: string; language: string; demo: boolean; duration: number };

function form(blob: Blob, chosen: string, durationMs: number): FormData {
  const { type, name } = uploadFile(blob.type, chosen);
  const body = new FormData();
  body.append("file", new File([blob], name, { type }));
  body.append("duration", (durationMs / 1000).toFixed(2));
  return body;
}

export function uploadRoomVoice(orgId: string, roomId: string, blob: Blob, chosen: string, durationMs: number) {
  return apiClientUpload<VoiceNoteRow>(`/orgs/${orgId}/rooms/${roomId}/voice`, form(blob, chosen, durationMs));
}

export function transcribeForBuddy(orgId: string, blob: Blob, chosen: string, durationMs: number) {
  return apiClientUpload<VoiceInputResult>(`/orgs/${orgId}/buddies/voice-input`, form(blob, chosen, durationMs));
}

/** The audio through the signed-in API (no public URL), as a blob the page can play. */
export async function fetchVoiceAudio(audioUrl: string): Promise<Blob> {
  const res = await apiClient.get<Blob>(`/api/v2${audioUrl}`, { responseType: "blob" });
  return res.data;
}

/** Arabic dialects by name; other languages by their usual name. */
export function languageLabel(code: string, tr: (text: string) => string): string {
  const value = (code || "").trim();
  if (!value) return "";
  if (value === "ar-EG") return tr("Egyptian Arabic");
  if (["ar-SA", "ar-AE", "ar-KW", "ar-QA", "ar-BH", "ar-OM"].includes(value)) return tr("Gulf Arabic");
  const names: Record<string, string> = {
    ar: tr("Arabic"),
    en: tr("English"),
    tr: tr("Turkish"),
    fr: tr("French"),
    pt: tr("Portuguese"),
  };
  return names[value.split("-")[0]] ?? value;
}

/** A message the voice list has not been checked for yet (it may be a new voice note). */
export function hasUnchecked(messageIds: string[], checked: Set<string>): boolean {
  return messageIds.some((id) => !checked.has(id));
}

/** A transcript is still being made: keep asking until it is done or failed. */
export function hasPending(notes: Record<string, VoiceNoteRow>): boolean {
  return Object.values(notes).some((n) => n.status === "pending");
}
