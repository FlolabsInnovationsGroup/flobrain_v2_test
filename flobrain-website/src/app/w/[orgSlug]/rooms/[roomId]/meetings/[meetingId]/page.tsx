"use client";

import "@livekit/components-styles";

import { LiveKitRoom, RoomAudioRenderer, VideoConference } from "@livekit/components-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";

type Join = { url?: string; token?: string; room: string; recording: boolean; can_manage: boolean; demo?: boolean; participants?: string[] };
type MeetingRow = { id: string; title: string };

/** A call inside FloBrain (our own LiveKit server). Everyone sees when it is being recorded. */
export default function CallPage() {
  const { orgSlug, roomId, meetingId } = useParams<{ orgSlug: string; roomId: string; meetingId: string }>();
  const { orgId } = useAccess();
  const router = useRouter();
  const tr = useTr();
  const [join, setJoin] = useState<Join | null>(null);
  const [title, setTitle] = useState("");
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const back = `/w/${orgSlug}/rooms/${roomId}/meetings`;

  useEffect(() => {
    if (!orgId) return;
    api
      .get<MeetingRow[]>(`/orgs/${orgId}/rooms/${roomId}/meetings`)
      .then((rows) => setTitle(rows.find((m) => m.id === meetingId)?.title ?? ""))
      .catch(() => undefined);
  }, [orgId, roomId, meetingId]);

  const enter = useCallback(async () => {
    if (!orgId) return;
    setError("");
    try {
      const res = await api.post<Join>(`/orgs/${orgId}/meetings/${meetingId}/join`);
      setJoin(res);
      setRecording(res.recording);
    } catch (err) {
      setError(errorText(err));
    }
  }, [orgId, meetingId]);

  // While in the call, check every 10 seconds whether recording started or the call ended.
  useEffect(() => {
    if (!join || !orgId) return;
    const timer = window.setInterval(() => {
      api
        .get<{ recording: boolean; ended: boolean }>(`/orgs/${orgId}/meetings/${meetingId}/state`)
        .then((s) => {
          setRecording(s.recording);
          if (s.ended) router.replace(back);
        })
        .catch(() => undefined);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [join, orgId, meetingId, router, back]);

  async function setRecordingState(action: "start" | "stop") {
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ recording: boolean }>(`/orgs/${orgId}/meetings/${meetingId}/recording`, { action });
      setRecording(res.recording);
    } catch (err) {
      setError(errorText(err));
    }
    setBusy(false);
  }

  async function endForAll() {
    setBusy(true);
    try {
      await api.post(`/orgs/${orgId}/meetings/${meetingId}/end`);
      router.replace(back);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-[80dvh] flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href={back} className="text-sm text-[color:var(--fb-v2-text-muted)] hover:underline">
            {tr("Back to meetings")}
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">{title || tr("Call")}</h1>
        </div>
        {join?.can_manage ? (
          <div className="flex gap-2">
            {recording ? (
              <Button variant="outline" disabled={busy} onClick={() => setRecordingState("stop")}>
                {tr("Stop recording")}
              </Button>
            ) : (
              <Button variant="waiting" disabled={busy} onClick={() => setRecordingState("start")}>
                {tr("Start recording")}
              </Button>
            )}
            <Button variant="danger" disabled={busy} onClick={endForAll}>
              {tr("End for everyone")}
            </Button>
          </div>
        ) : null}
      </div>
      {recording ? (
        <p role="status" className="mb-3 rounded-lg bg-[color:var(--fb-v2-error)] px-4 py-2 text-sm font-medium text-black">
          {tr("This call is being recorded. It will be transcribed and summarized for this room.")}
        </p>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {!join ? (
        <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-6">
          <p className="mb-4 text-[color:var(--fb-v2-text-muted)]">
            {tr("You join with your camera and microphone off. Turn them on from the bar at the bottom.")}
          </p>
          <Button onClick={enter} disabled={!orgId}>
            {tr("Join the call")}
          </Button>
        </div>
      ) : join.demo ? (
        <DemoCall people={join.participants ?? []} onLeave={() => router.replace(back)} />
      ) : (
        <div data-lk-theme="default" className="min-h-[70dvh] flex-1 overflow-hidden rounded-xl">
          <LiveKitRoom serverUrl={join.url ?? ""} token={join.token ?? ""} connect audio={false} video={false} onDisconnected={() => router.replace(back)} style={{ height: "70dvh" }}>
            <VideoConference />
            <RoomAudioRenderer />
          </LiveKitRoom>
        </div>
      )}
    </div>
  );
}

/** The demo call: no call server, so the people in the room appear as tiles and take turns speaking. */
function DemoCall({ people, onLeave }: { people: string[]; onLeave: () => void }) {
  const tr = useTr();
  const [mic, setMic] = useState(false);
  const [camera, setCamera] = useState(false);
  const [speaking, setSpeaking] = useState(1);

  useEffect(() => {
    const timer = window.setInterval(() => setSpeaking((n) => (n + 1) % Math.max(people.length, 1)), 3000);
    return () => window.clearInterval(timer);
  }, [people.length]);

  return (
    <div className="flex min-h-[60dvh] flex-1 flex-col rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Demo call: no call server is connected, so the other people here are simulated. Recording produces a sample transcript by speaker.")}
      </p>
      <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {people.map((name, i) => (
          <div
            key={name + i}
            className={`flex min-h-40 flex-col items-center justify-center rounded-xl bg-[color:var(--fb-v2-raised)] p-4 ${
              i === speaking && (i !== 0 || mic) ? "ring-2 ring-[color:var(--fb-v2-accent)]" : ""
            }`}
          >
            <span className="mb-2 flex h-16 w-16 items-center justify-center rounded-full bg-[color:var(--fb-v2-accent)] text-xl font-semibold text-white" aria-hidden>
              {name.slice(0, 1).toUpperCase()}
            </span>
            <span className="font-medium">{i === 0 ? tr("{name} (you)", { name }) : name}</span>
            <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
              {i === 0 ? (mic ? tr("Microphone on") : tr("Muted")) : i === speaking ? tr("Speaking") : tr("Listening")}
              {i === 0 && camera ? `, ${tr("camera on")}` : ""}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <Button variant="outline" onClick={() => setMic((v) => !v)} aria-pressed={mic}>
          {mic ? tr("Mute") : tr("Unmute")}
        </Button>
        <Button variant="outline" onClick={() => setCamera((v) => !v)} aria-pressed={camera}>
          {camera ? tr("Turn camera off") : tr("Turn camera on")}
        </Button>
        <Button variant="danger" onClick={onLeave}>
          {tr("Leave")}
        </Button>
      </div>
    </div>
  );
}
