"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ActionItemTask } from "@/components/v2/screens/ActionItemTask";
import { MeetingBotInvite } from "@/components/v2/screens/MeetingBotInvite";
import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { flag, has } from "@/lib/v2/access";
import { api, apiClientUpload, errorText } from "@/lib/v2/api";
import { v2Client } from "@/lib/v2/client";
import { canShowJoinUrl, duration, meetingsEmpty, sortRecordings, type MeetingRow, type RecordingRow } from "@/lib/v2/screens/meetings";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

type Summary = { text: string; decisions: string[]; action_items: { id: string; text?: string; title?: string; owner?: string; task_id?: string }[] };
type BotSession = { id: string; platform: string; status: string; error: string; created_at: string };
type MeetingTranscript = { segments: { start: number; end: number; speaker: string; text: string }[]; speakers: string[] };
type Transcript = { text: string; segments: { start: number; end: number; text: string }[] };

const TRANSCRIPT_STATUS: Record<string, string> = { none: "Not transcribed", queued: "Waiting to transcribe", running: "Transcribing", done: "Transcribed", failed: "Transcription failed" };
const BOT_STATUS: Record<string, string> = {
  requested: "Waiting for the assistant",
  joining: "Joining",
  waiting_admission: "Waiting for the host to let it in",
  in_call: "In the meeting, recording",
  uploading: "Uploading the recording",
  done: "Finished",
  failed: "Couldn't join",
  cancelled: "Removed",
};
const SOURCE: Record<string, string> = { upload: "Uploaded", livekit: "FloBrain call", bot: "Assistant in Zoom, Meet or Teams" };

/** Meetings in a room: calls inside FloBrain, recordings, transcripts and summaries with action items. */
export function MeetingsScreen({ orgSlug, roomId }: { orgSlug: string; roomId: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const { access } = useAccess();
  const tr = useTr();
  const manager = has(access, "meeting.manage");
  const calls = flag(access, "voice_video");
  const [meetings, setMeetings] = useState<MeetingRow[]>([]);
  const [recordings, setRecordings] = useState<RecordingRow[]>([]);
  const [newestFirst, setNewestFirst] = useState(true);
  const [loadState, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [bots, setBots] = useState<BotSession[]>([]);
  const [transcript, setTranscript] = useState<{ id: string; data: Transcript } | null>(null);
  const [whole, setWhole] = useState<{ id: string; data: MeetingTranscript } | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const fetchNow = useCallback(() => {
    if (!orgId) return;
    Promise.all([v2Client().meetings(orgId, roomId), v2Client().recordings(orgId, roomId, newestFirst ? "-recorded_at" : "recorded_at")])
      .then(([meetingRows, recordingPage]) => {
        const nextMeetings = meetingRows as MeetingRow[];
        const nextRecordings = (recordingPage.results ?? []) as RecordingRow[];
        setMeetings(nextMeetings);
        setRecordings(nextRecordings);
        setState(meetingsEmpty(nextMeetings, nextRecordings) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError(tr("Could not load meetings"));
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, roomId, newestFirst, tr]);

  const state = orgState === "ready" ? loadState : orgState;

  const load = useCallback(() => {
    setState("loading");
    fetchNow();
  }, [fetchNow]);

  useEffect(() => {
    if (orgState === "ready") fetchNow();
  }, [orgState, fetchNow]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: tr(ok) });
      load();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  // While the assistant is on its way or in the call, refresh its status (and the summary when it's done).
  const active = bots.some((b) => ["requested", "joining", "waiting_admission", "in_call", "uploading"].includes(b.status));
  useEffect(() => {
    if (!open || !orgId) return;
    const id = open;
    const timer = window.setInterval(() => {
      api
        .get<BotSession[]>(`/orgs/${orgId}/meetings/${id}/bot-sessions`)
        .then((rows) => {
          setBots(rows);
          if (!rows.some((b) => ["requested", "joining", "waiting_admission", "in_call", "uploading"].includes(b.status))) {
            api.get<Summary>(`/orgs/${orgId}/meetings/${id}/summary`).then(setSummary).catch(() => undefined);
            fetchNow();
          }
        })
        .catch(() => undefined);
    }, 4000);
    if (!active) window.clearInterval(timer);
    return () => window.clearInterval(timer);
  }, [open, orgId, active, fetchNow]);

  async function openMeeting(id: string) {
    setOpen(open === id ? null : id);
    setSummary(null);
    setBots([]);
    if (open === id || !orgId) return;
    api.get<BotSession[]>(`/orgs/${orgId}/meetings/${id}/bot-sessions`).then(setBots).catch(() => setBots([]));
    try {
      setSummary(await api.get<Summary>(`/orgs/${orgId}/meetings/${id}/summary`));
    } catch {
      setSummary(null);
    }
  }

  async function showTranscript(id: string) {
    if (transcript?.id === id) return setTranscript(null);
    try {
      setTranscript({ id, data: await api.get<Transcript>(`/orgs/${orgId}/recordings/${id}/transcript`) });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function showWhole(id: string) {
    if (whole?.id === id) return setWhole(null);
    try {
      setWhole({ id, data: await api.get<MeetingTranscript>(`/orgs/${orgId}/meetings/${id}/transcript`) });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function upload(meetingId: string, file: File | undefined) {
    if (!file || !orgId) return;
    const body = new FormData();
    body.append("file", file);
    await act(() => apiClientUpload(`/orgs/${orgId}/meetings/${meetingId}/recordings`, body), "Recording added. It will be transcribed.");
  }

  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">{tr("Meetings")}</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="meetings" />
      {manager && orgId ? (
        <form
          className="mb-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => v2Client().createMeeting(orgId, roomId, title || tr("Meeting")), "Meeting created.").then(() => setTitle(""));
          }}
        >
          <label className="text-sm">
            <span className="mb-1 block font-medium">{tr("New meeting")}</span>
            <input className="v2-input w-72" maxLength={200} placeholder={tr("Weekly sync")} value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <Button type="submit">{tr("Create")}</Button>
        </form>
      ) : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error || orgError} emptyLabel={tr("No meetings yet")} onRetry={load}>
        <div className="space-y-6">
          <Rows>
            {meetings.map((meeting) => {
              const recs = recordings.filter((r) => r.meeting === meeting.id);
              const canManage = meeting.can_manage ?? manager;
              return (
                <Row key={meeting.id} className="items-start">
                  <div className="min-w-0 flex-1">
                    <button type="button" className="text-start font-medium hover:underline" onClick={() => openMeeting(meeting.id)} aria-expanded={open === meeting.id}>
                      {meeting.title}
                    </button>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {when(meeting.started_at)}
                      {meeting.ended_at ? ` · ${tr("Ended")}` : ""}
                      {meeting.has_summary ? ` · ${tr("Summary ready")}` : ""}
                    </p>
                    {meeting.recording ? <Badge tone="bad">{tr("Recording")}</Badge> : null}
                    {open === meeting.id ? (
                      <div className="mt-3 space-y-3">
                        {summary ? (
                          <div className="rounded-lg bg-[color:var(--fb-v2-bg)] p-3 text-sm">
                            <p className="whitespace-pre-wrap">{summary.text}</p>
                            {summary.decisions.length ? (
                              <>
                                <h3 className="mt-3 font-semibold">{tr("Decisions")}</h3>
                                <ul className="list-disc ps-5">
                                  {summary.decisions.map((d, i) => (
                                    <li key={i}>{d}</li>
                                  ))}
                                </ul>
                              </>
                            ) : null}
                            {summary.action_items.length ? (
                              <>
                                <h3 className="mt-3 font-semibold">{tr("Action items")}</h3>
                                <ul className="space-y-1">
                                  {summary.action_items.map((item, i) => (
                                    <li key={item.id ?? i} className="flex flex-wrap items-center justify-between gap-2">
                                      <span>
                                        {item.text || item.title}
                                        {item.owner ? <span className="text-[color:var(--fb-v2-text-muted)]"> ({item.owner})</span> : null}
                                      </span>
                                      {item.id && orgId ? (
                                        <ActionItemTask
                                          orgId={orgId}
                                          orgSlug={orgSlug}
                                          meetingId={meeting.id}
                                          item={item}
                                          onDone={(text) => {
                                            setMessage({ kind: "ok", text });
                                            api.get<Summary>(`/orgs/${orgId}/meetings/${meeting.id}/summary`).then(setSummary).catch(() => undefined);
                                          }}
                                        />
                                      ) : null}
                                    </li>
                                  ))}
                                </ul>
                              </>
                            ) : null}
                          </div>
                        ) : (
                          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No summary yet. It appears after a recording is transcribed.")}</p>
                        )}
                        {bots.length ? (
                          <ul className="space-y-1 text-sm">
                            {bots.map((b) => (
                              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2">
                                <span>
                                  {tr("Assistant in {platform}", { platform: b.platform === "meet" ? "Google Meet" : b.platform === "teams" ? "Teams" : "Zoom" })}: {tr(BOT_STATUS[b.status] ?? b.status)}
                                  {b.error ? <span className="text-[color:var(--fb-v2-text-muted)]"> ({b.error})</span> : null}
                                </span>
                                {canManage && ["requested", "joining", "waiting_admission", "in_call"].includes(b.status) ? (
                                  <Button
                                    variant="outline"
                                    onClick={() =>
                                      act(() => api.post(`/orgs/${orgId}/meetings/${meeting.id}/bot-sessions/${b.id}/cancel`), "The assistant will leave the meeting.").then(() =>
                                        api.get<BotSession[]>(`/orgs/${orgId}/meetings/${meeting.id}/bot-sessions`).then(setBots),
                                      )
                                    }
                                  >
                                    {tr("Remove assistant")}
                                  </Button>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                        {recs.some((r) => r.transcript_status === "done") ? (
                          <div>
                            <Button variant="outline" onClick={() => showWhole(meeting.id)}>
                              {whole?.id === meeting.id ? tr("Hide the full transcript") : tr("Read the full transcript")}
                            </Button>
                            {whole?.id === meeting.id ? (
                              <ol className="mt-2 max-h-96 space-y-1 overflow-y-auto rounded-lg bg-[color:var(--fb-v2-bg)] p-3 text-sm">
                                {whole.data.segments.map((seg, i) => (
                                  <li key={i}>
                                    <span className="me-2 tabular-nums text-[color:var(--fb-v2-text-muted)]">{duration(Math.floor(seg.start)) || "0:00"}</span>
                                    {seg.speaker ? <span className="me-1 font-semibold">{seg.speaker}:</span> : null}
                                    {seg.text}
                                  </li>
                                ))}
                              </ol>
                            ) : null}
                          </div>
                        ) : null}
                        {recs.length ? (
                          <ul className="space-y-2 text-sm">
                            {recs.map((r) => (
                              <li key={r.id} className="rounded-lg p-2 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span>
                                    {r.speaker ? `${r.speaker} · ` : ""}
                                    {tr(SOURCE[r.source ?? "upload"] ?? "Uploaded")} · {when(r.recorded_at)}
                                    {duration(r.duration_seconds) ? ` · ${duration(r.duration_seconds)}` : ""}
                                  </span>
                                  <Badge tone={r.transcript_status === "done" ? "good" : r.transcript_status === "failed" ? "bad" : "neutral"}>
                                    {tr(TRANSCRIPT_STATUS[r.transcript_status ?? "none"] ?? "Not transcribed")}
                                  </Badge>
                                </div>
                                {r.transcript_error ? <p className="text-[color:var(--fb-v2-text-muted)]">{r.transcript_error}</p> : null}
                                <div className="mt-1 flex flex-wrap gap-2">
                                  {r.transcript_status === "done" ? (
                                    <Button variant="ghost" onClick={() => showTranscript(r.id)}>
                                      {transcript?.id === r.id ? tr("Hide transcript") : tr("Read transcript")}
                                    </Button>
                                  ) : null}
                                  {canManage && (r.transcript_status === "none" || r.transcript_status === "failed") ? (
                                    <Button variant="ghost" onClick={() => act(() => api.post(`/orgs/${orgId}/recordings/${r.id}/transcribe`), "Transcription started.")}>
                                      {tr("Transcribe")}
                                    </Button>
                                  ) : null}
                                </div>
                                {transcript?.id === r.id ? (
                                  <ol className="mt-2 max-h-80 space-y-1 overflow-y-auto">
                                    {(transcript.data.segments.length ? transcript.data.segments : [{ start: 0, end: 0, text: transcript.data.text }]).map((seg, i) => (
                                      <li key={i}>
                                        <span className="me-2 tabular-nums text-[color:var(--fb-v2-text-muted)]">{duration(Math.floor(seg.start)) || "0:00"}</span>
                                        {seg.text}
                                      </li>
                                    ))}
                                  </ol>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                        {canManage ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <label className="text-sm">
                              <span className="me-2">{tr("Add a recording")}</span>
                              <input type="file" accept="audio/*,video/mp4,video/webm" onChange={(e) => upload(meeting.id, e.target.files?.[0])} />
                            </label>
                            <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/meetings/${meeting.id}/summarize`), "Summary updated.")}>
                              {tr("Summarize again")}
                            </Button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {calls && meeting.call_available ? (
                      <Link href={`/w/${orgSlug}/rooms/${roomId}/meetings/${meeting.id}`}>
                        <Button>{tr("Join the call")}</Button>
                      </Link>
                    ) : null}
                    {canShowJoinUrl(meeting.join_url) ? (
                      <a href={meeting.join_url} className="text-[color:var(--fb-v2-accent)]">
                        {tr("Join")}
                      </a>
                    ) : null}
                    {orgId && canManage && !meeting.ended_at ? <MeetingBotInvite
                        orgId={orgId}
                        roomId={roomId}
                        meetingId={meeting.id}
                        onInvited={() => {
                          if (open !== meeting.id) void openMeeting(meeting.id);
                          else api.get<BotSession[]>(`/orgs/${orgId}/meetings/${meeting.id}/bot-sessions`).then(setBots).catch(() => undefined);
                        }}
                      /> : null}
                  </div>
                </Row>
              );
            })}
          </Rows>
          {recordings.some((r) => !meetings.find((m) => m.id === r.meeting)) ? (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold">{tr("Recordings")}</h2>
                <Button type="button" variant="ghost" onClick={() => setNewestFirst((value) => !value)}>
                  {newestFirst ? tr("Newest first") : tr("Oldest first")}
                </Button>
              </div>
              <ul className="space-y-1">
                {sortRecordings(recordings, newestFirst).map((row) => (
                  <li key={row.id}>{row.recorded_at.slice(0, 10)}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </ScreenBody>
    </section>
  );
}
