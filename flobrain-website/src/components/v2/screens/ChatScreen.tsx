"use client";

import { useCallback, useEffect, useState } from "react";

import { useRoomMessages } from "@/lib/v2/useRoomMessages";

import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import {
  canSendMessage,
  displayBody,
  formatRoomTimestamp,
  loadCursorPages,
  type ChatMessage,
} from "@/lib/v2/screens/chat";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function ChatScreen({ orgSlug, roomId }: { orgSlug: string; roomId: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [roomName, setRoomName] = useState("Room");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    Promise.all([
      v2Client().room(orgId, roomId),
      loadCursorPages((cursor) => v2Client().roomMessages(orgId, roomId, undefined, cursor)),
    ])
      .then(([room, rows]) => {
        setRoomName(String(room.name ?? "Room"));
        setMessages(rows);
        setState(rows.length === 0 ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load chat");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, roomId]);

  useEffect(() => {
    if (orgState === "ready") {
      setState("loading");
      load();
    } else setState(orgState);
  }, [orgState, load]);

  useRoomMessages(load, state === "ready" || state === "empty");

  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">{roomName}</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="chat" />
      <ScreenBody state={state} error={error || orgError} emptyLabel="No messages yet" onRetry={load}>
        <ul className="space-y-3">
          {messages.map((message) => (
            <li key={message.id}>
              <p>{displayBody(message, false)}</p>
              <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                {formatRoomTimestamp(message.created_at)}
              </p>
            </li>
          ))}
        </ul>
      </ScreenBody>
      <form
        className="mt-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!orgId || !canSendMessage(draft)) return;
          v2Client()
            .postMessage(orgId, roomId, draft)
            .then(() => {
              setDraft("");
              load();
            });
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-3 py-2"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Write a message"
        />
        <Button type="submit">Send</Button>
      </form>
    </section>
  );
}
