"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useTr } from "@/i18n/phrases";
import { api } from "@/lib/v2/api";

import { VoiceNotePlayer } from "./VoiceNotePlayer";
import { VoiceRecorder } from "./VoiceRecorder";
import { hasPending, hasUnchecked, uploadRoomVoice, type VoiceNoteRow } from "./voiceApi";

const PENDING_POLL_MS = 4000;

/**
 * Voice notes of a room, keyed by message id, translated to ``language`` when they were spoken
 * in another one. Fetches again when new messages appear and while a transcript is pending.
 */
export function useRoomVoiceNotes(orgId: string | null, roomId: string, messageIds: string[], enabled: boolean, language: string) {
  const [notes, setNotes] = useState<Record<string, VoiceNoteRow>>({});
  const checked = useRef<Set<string>>(new Set());
  const inFlight = useRef(false);
  const idsKey = messageIds.join(",");

  const reload = useCallback(() => {
    if (!orgId || !enabled || inFlight.current) return;
    inFlight.current = true;
    const asked = idsKey ? idsKey.split(",") : [];
    api
      .get<{ results?: VoiceNoteRow[] }>(`/orgs/${orgId}/rooms/${roomId}/voice`, language ? { translate_to: language } : undefined)
      .then((page) => {
        const next: Record<string, VoiceNoteRow> = {};
        for (const row of page.results ?? []) next[row.message] = row;
        for (const id of asked) checked.current.add(id);
        setNotes(next);
      })
      .catch(() => undefined)
      .finally(() => {
        inFlight.current = false;
      });
  }, [orgId, roomId, enabled, language, idsKey]);

  useEffect(() => {
    checked.current = new Set();
  }, [roomId, language]);

  useEffect(() => {
    if (hasUnchecked(idsKey ? idsKey.split(",") : [], checked.current)) reload();
  }, [idsKey, reload]);

  const pending = hasPending(notes);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(reload, PENDING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pending, reload]);

  return { notes, reload };
}

/** The room composer's record button: posts the recording as a voice message. */
export function RoomVoiceRecorder({ orgId, roomId, onSent }: { orgId: string; roomId: string; onSent: () => void }) {
  const tr = useTr();
  return (
    <VoiceRecorder
      label={tr("Record a voice note for this room")}
      busyLabel={tr("Sending…")}
      onRecorded={async (blob, type, ms) => {
        await uploadRoomVoice(orgId, roomId, blob, type, ms);
        onSent();
      }}
    />
  );
}

/** A voice message in the room timeline. */
export function RoomVoiceNote({ orgId, roomId, note, mine, onChanged }: { orgId: string; roomId: string; note: VoiceNoteRow; mine: boolean; onChanged: () => void }) {
  return (
    <VoiceNotePlayer
      note={note}
      onRetry={
        mine
          ? async () => {
              await api.post(`/orgs/${orgId}/rooms/${roomId}/voice/${note.id}/retry`);
              onChanged();
            }
          : undefined
      }
    />
  );
}
