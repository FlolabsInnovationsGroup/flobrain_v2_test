"use client";

import { useCallback, useEffect, useState } from "react";

import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import {
  canShowJoinUrl,
  meetingsEmpty,
  sortRecordings,
  type MeetingRow,
  type RecordingRow,
} from "@/lib/v2/screens/meetings";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function MeetingsScreen({ orgSlug, roomId }: { orgSlug: string; roomId: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [meetings, setMeetings] = useState<MeetingRow[]>([]);
  const [recordings, setRecordings] = useState<RecordingRow[]>([]);
  const [newestFirst, setNewestFirst] = useState(true);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    Promise.all([
      v2Client().meetings(orgId, roomId),
      v2Client().recordings(orgId, roomId, newestFirst ? "-recorded_at" : "recorded_at"),
    ])
      .then(([meetingRows, recordingPage]) => {
        const nextMeetings = meetingRows as MeetingRow[];
        const nextRecordings = (recordingPage.results ?? []) as RecordingRow[];
        setMeetings(nextMeetings);
        setRecordings(nextRecordings);
        setState(meetingsEmpty(nextMeetings, nextRecordings) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load meetings");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, roomId, newestFirst]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">Meetings</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="meetings" />
      <ScreenBody state={state} error={error || orgError} emptyLabel="No meetings yet" onRetry={load}>
        <div className="space-y-6">
          <ul className="space-y-2">
            {meetings.map((meeting) => (
              <li key={meeting.id} className="flex items-center justify-between gap-2">
                <span>{meeting.title}</span>
                {canShowJoinUrl(meeting.join_url) ? (
                  <a href={meeting.join_url} className="text-[color:var(--fb-v2-accent)]">
                    Join
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">Recordings</h2>
              <Button type="button" variant="ghost" onClick={() => setNewestFirst((value) => !value)}>
                {newestFirst ? "Newest first" : "Oldest first"}
              </Button>
            </div>
            <ul className="space-y-1">
              {sortRecordings(recordings, newestFirst).map((row) => (
                <li key={row.id}>
                  <a href={row.play_url}>{row.recorded_at.slice(0, 10)}</a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </ScreenBody>
    </section>
  );
}
