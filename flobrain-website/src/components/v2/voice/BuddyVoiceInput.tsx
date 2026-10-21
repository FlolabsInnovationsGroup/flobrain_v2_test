"use client";

import { useState } from "react";

import { useTr } from "@/i18n/phrases";

import { VoiceRecorder } from "./VoiceRecorder";
import { transcribeForBuddy } from "./voiceApi";

/**
 * Speak to a buddy: the recording is turned into text and put in the composer so the person
 * can check it before sending. The server keeps neither the audio nor the text.
 */
export function BuddyVoiceInput({ orgId, onTranscript, disabled }: { orgId: string; onTranscript: (text: string) => void; disabled?: boolean }) {
  const tr = useTr();
  const [note, setNote] = useState("");
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <VoiceRecorder
        disabled={disabled}
        label={tr("Speak your message")}
        busyLabel={tr("Transcribing…")}
        onRecorded={async (blob, type, ms) => {
          setNote("");
          const res = await transcribeForBuddy(orgId, blob, type, ms);
          onTranscript(res.text);
          setNote(res.demo ? tr("Demo transcript. Check the text, then send.") : tr("Check the text, then send."));
        }}
      />
      {note ? (
        <p role="status" className="text-xs text-[color:var(--fb-v2-text-muted)]">
          {note}
        </p>
      ) : null}
    </div>
  );
}
