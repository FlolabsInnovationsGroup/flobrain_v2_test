"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { mediaUrl, type Asset } from "./model";

type Info = { provider: string; label: string; demo: boolean; voices: { id: string; label: string; language: string }[]; max_chars: number };

/** Script to voiceover: the audio becomes a recording of this project (use it as music or narration). */
export function VoiceoverPanel({ orgId, projectId, onAdded }: { orgId: string | null; projectId?: string; onAdded?: (asset: Asset) => void }) {
  const tr = useTr();
  const info = useOrgData<Info>(orgId, "/content/voiceover");
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<(Asset & { demo?: boolean }) | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (info.state === "off") {
    return <Notice>{tr("Voiceover is not set up. A text-to-speech provider has not been chosen yet.")}</Notice>;
  }
  if (info.state !== "ready" || !info.data) return null;
  const data = info.data;

  async function make() {
    setBusy(true);
    setMessage(null);
    try {
      const asset = await api.post<Asset & { demo?: boolean }>(`/orgs/${orgId}/content/voiceover`, {
        text,
        voice: voice || data.voices[0]?.id,
        project: projectId,
      });
      setMade(asset);
      onAdded?.(asset);
    } catch (err) {
      setMessage(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        make();
      }}
    >
      {data.demo ? <Notice>{tr("Demo voice: every script plays the same sample audio.")}</Notice> : null}
      <Field label={tr("Script")} hint={tr("{n} of {max} characters", { n: text.length, max: data.max_chars })}>
        <textarea className="v2-input min-h-28" required maxLength={data.max_chars} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <Field label={tr("Voice")}>
        <select className="v2-input" value={voice || data.voices[0]?.id || ""} onChange={(e) => setVoice(e.target.value)}>
          {data.voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label} ({v.language})
            </option>
          ))}
        </select>
      </Field>
      <p className="mb-3 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Voices are stock voices. Cloning a real person's voice is not offered.")}</p>
      <Button type="submit" disabled={busy || !text.trim()}>
        {busy ? tr("Making the voiceover") : tr("Make voiceover")}
      </Button>
      {message ? <Notice kind="error">{message}</Notice> : null}
      {made ? (
        <div className="mt-3">
          <Notice kind="ok">{projectId ? tr("Voiceover added to this project.") : tr("Voiceover saved to your library.")}</Notice>
          {made.url ? <audio className="mt-1 w-full" controls src={mediaUrl(made.url)} /> : null}
        </div>
      ) : null}
    </form>
  );
}
