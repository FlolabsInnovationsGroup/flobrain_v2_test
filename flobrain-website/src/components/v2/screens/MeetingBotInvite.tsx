"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

/** Invite the meeting assistant. It announces itself, and a recording notice is posted to the room first. */
export function MeetingBotInvite({ orgId, roomId, meetingId, onInvited }: { orgId: string; roomId: string; meetingId: string; onInvited?: () => void }) {
  const tr = useTr();
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState("meet");
  const [url, setUrl] = useState("");
  const [consent, setConsent] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        {tr("Invite assistant")}
      </Button>
    );
  }
  return (
    <form
      className="mt-2 w-full rounded-lg p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]"
      onSubmit={async (e) => {
        e.preventDefault();
        setMessage(null);
        try {
          await api.post(`/orgs/${orgId}/rooms/${roomId}/meetings/${meetingId}/bot`, { platform, meeting_url: url, host_consent: consent });
          setMessage({ kind: "ok", text: tr("Invited. A recording notice was posted in this room.") });
          onInvited?.();
        } catch (err) {
          setMessage({ kind: "error", text: errorText(err) });
        }
      }}
    >
      <div className="flex flex-wrap gap-2">
        <select className="v2-input w-32" value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label={tr("Platform")}>
          <option value="meet">Google Meet</option>
          <option value="zoom">Zoom</option>
          <option value="teams">Teams</option>
        </select>
        <input className="v2-input min-w-64 flex-1" type="url" required placeholder={tr("Meeting link")} value={url} onChange={(e) => setUrl(e.target.value)} />
      </div>
      <label className="mt-2 flex items-center gap-2">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        {tr("The host agrees to recording. Everyone will see a recording notice.")}
      </label>
      <Button className="mt-2" type="submit" disabled={!consent}>
        {tr("Invite the assistant")}
      </Button>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
    </form>
  );
}
