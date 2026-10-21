"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useRoomMessages } from "@/lib/v2/useRoomMessages";

import { AnnouncementsPanel } from "@/components/v2/rooms/AnnouncementsPanel";
import { mentionParts, roomTime, roomTitle, translateTarget } from "@/components/v2/rooms/format";
import { RoomMembersPanel, type RoomMemberRow } from "@/components/v2/rooms/RoomMembersPanel";
import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { RoomVoiceNote, RoomVoiceRecorder, useRoomVoiceNotes } from "@/components/v2/voice/RoomVoice";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Avatar, Notice } from "@/components/v2/ui/kit";
import { useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText } from "@/lib/v2/api";
import { v2Client } from "@/lib/v2/client";
import * as outbox from "@/lib/v2/outbox";
import { canSendMessage, loadCursorPages, type ChatMessage } from "@/lib/v2/screens/chat";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

const isNetworkError = (err: unknown) => !(err as { response?: unknown })?.response;

type Message = ChatMessage & { author_name?: string; edited_at?: string | null; translation_error?: string };
type Translated = { text?: string; error?: string };

function Body({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap break-words">
      {mentionParts(text).map((part, i) =>
        part.mention ? (
          <span key={i} className="font-medium text-[color:var(--fb-v2-accent)]">
            {part.text}
          </span>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </p>
  );
}

function MessageItem({
  message,
  mine,
  translation,
  translating,
  demo,
  onSave,
  onDelete,
  voice,
}: {
  message: Message;
  mine: boolean;
  translation?: Translated;
  translating: boolean;
  demo: boolean;
  onSave: (body: string) => Promise<boolean>;
  onDelete: () => Promise<boolean>;
  /** A voice note player (flag voice_notes), shown instead of the text. */
  voice?: React.ReactNode;
}) {
  const tr = useTr();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.body);
  const [confirming, setConfirming] = useState(false);
  const name = message.author_name || tr("Member");
  const shown = translating && translation?.text && translation.text !== message.body;

  return (
    <li className="group flex gap-3">
      <Avatar name={name} size={32} />
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <span className="font-semibold">{name}</span>{" "}
          <time dateTime={message.created_at} title={new Date(message.created_at).toLocaleString()} className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {roomTime(message.created_at, tr)}
          </time>
          {message.edited_at ? <span className="text-xs text-[color:var(--fb-v2-text-muted)]"> · {tr("edited")}</span> : null}
        </p>
        {editing ? (
          <form
            className="mt-1 flex flex-col gap-2 sm:flex-row"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!canSendMessage(draft)) return;
              if (await onSave(draft)) setEditing(false);
            }}
          >
            <input className="v2-input" value={draft} maxLength={8000} onChange={(event) => setDraft(event.target.value)} aria-label={tr("Edit message")} autoFocus />
            <div className="flex gap-2">
              <Button type="submit" disabled={!canSendMessage(draft)}>
                {tr("Save")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setDraft(message.body);
                  setEditing(false);
                }}
              >
                {tr("Cancel")}
              </Button>
            </div>
          </form>
        ) : voice ? (
          voice
        ) : shown ? (
          <>
            <Body text={translation.text ?? ""} />
            <details className="text-xs text-[color:var(--fb-v2-text-muted)]">
              <summary className="cursor-pointer">{demo ? tr("Translated by the demo model. Show original") : tr("Translated. Show original")}</summary>
              <p className="mt-1 whitespace-pre-wrap">{message.body}</p>
            </details>
          </>
        ) : (
          <Body text={message.body} />
        )}
        {translating && translation?.error ? (
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Translation not available for this message")}</p>
        ) : null}
        {mine && !editing ? (
          <div className="mt-1 flex gap-1 text-xs">
            {confirming ? (
              <>
                <span className="self-center text-[color:var(--fb-v2-text-muted)]">{tr("Delete this message?")}</span>
                <Button type="button" variant="danger" className="px-2 py-1 text-xs" onClick={() => onDelete().then(() => setConfirming(false))}>
                  {tr("Delete")}
                </Button>
                <Button type="button" variant="ghost" className="px-2 py-1 text-xs" onClick={() => setConfirming(false)}>
                  {tr("Keep it")}
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  variant="ghost"
                  className="px-2 py-1 text-xs"
                  onClick={() => {
                    setDraft(message.body);
                    setEditing(true);
                  }}
                >
                  {tr("Edit")}
                </Button>
                <Button type="button" variant="ghost" className="px-2 py-1 text-xs" onClick={() => setConfirming(true)}>
                  {tr("Delete")}
                </Button>
              </>
            )}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function ChatScreen({ orgSlug, roomId }: { orgSlug: string; roomId: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const { access } = useAccess();
  const tr = useTr();
  const locale = useLocale();
  const [roomName, setRoomName] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [members, setMembers] = useState<RoomMemberRow[]>([]);
  const [showMembers, setShowMembers] = useState(false);
  const [draft, setDraft] = useState("");
  const [loadState, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [translating, setTranslating] = useState(false);
  const [translations, setTranslations] = useState<Record<string, Translated>>({});
  const [translateNote, setTranslateNote] = useState("");
  const asked = useRef<Set<string>>(new Set());

  const selfId = access?.user_id;
  const canTranslate = flag(access, "live_translation");
  const voiceOn = flag(access, "voice_notes");
  const canAnnounce = has(access, "announcement.manage");
  const target = translateTarget(locale);
  const voice = useRoomVoiceNotes(orgId, roomId, messages.map((m) => m.id), voiceOn, target);

  const load = useCallback(() => {
    if (!orgId) return;
    Promise.all([
      v2Client().room(orgId, roomId),
      loadCursorPages((cursor) =>
        v2Client().roomMessages(orgId, roomId, undefined, cursor) as Promise<{ results?: Message[]; next?: string | null }>,
      ),
    ])
      .then(([room, rows]) => {
        setRoomName(roomTitle({ name: String(room.name ?? ""), kind: String(room.kind ?? ""), other_name: room.other_name as string | undefined }));
        setMessages(rows as Message[]);
        setState(rows.length === 0 ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError(tr("Could not load chat"));
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, roomId, tr]);

  const loadMembers = useCallback(() => {
    if (!orgId) return;
    api
      .get<RoomMemberRow[]>(`/orgs/${orgId}/rooms/${roomId}/members`)
      .then(setMembers)
      .catch(() => setMembers([]));
  }, [orgId, roomId]);

  // Until the workspace resolves, show its state. The first fetch starts in "loading"; setState runs only in callbacks.
  const state = orgState === "ready" ? loadState : orgState;

  useEffect(() => {
    if (orgState === "ready") {
      load();
      loadMembers();
    }
  }, [orgState, load, loadMembers]);

  useRoomMessages(load, state === "ready" || state === "empty");

  // Translations are fetched only for messages not asked about yet (the server caches them), not on every poll.
  useEffect(() => {
    if (!orgId || !translating) return;
    const missing = messages.filter((m) => !asked.current.has(`${target}:${m.id}:${m.edited_at ?? ""}`));
    if (!missing.length) return;
    for (const m of missing) asked.current.add(`${target}:${m.id}:${m.edited_at ?? ""}`);
    api
      .get<{ results?: Message[] }>(`/orgs/${orgId}/rooms/${roomId}/messages`, { translate_to: target })
      .then((page) => {
        const next: Record<string, Translated> = {};
        for (const row of page.results ?? []) {
          next[row.id] = row.translated ? { text: row.translation } : { error: row.translation_error || "unavailable" };
        }
        setTranslations((prev) => ({ ...prev, ...next }));
      })
      .catch((err) => {
        const e = apiError(err);
        for (const m of missing) asked.current.delete(`${target}:${m.id}:${m.edited_at ?? ""}`);
        setTranslating(false);
        if (e.status === 501) setTranslateNote(tr("Live translation is not set up for your organization."));
        else setTranslateNote(errorText(err));
      });
  }, [orgId, roomId, messages, translating, target, tr]);

  const [queued, setQueued] = useState(0);
  useEffect(() => {
    if (!orgId) return;
    const send = () =>
      outbox
        .flush((row) => v2Client().postMessage(row.orgId, row.roomId, row.body), isNetworkError)
        .then((sent) => {
          setQueued(outbox.pending(roomId).length);
          if (sent) load();
        });
    const initial = window.setTimeout(send, 0);
    window.addEventListener("online", send);
    return () => {
      window.clearTimeout(initial);
      window.removeEventListener("online", send);
    };
  }, [orgId, roomId, load]);

  async function saveEdit(message: Message, body: string) {
    setActionError("");
    try {
      await api.patch(`/orgs/${orgId}/rooms/${roomId}/messages/${message.id}`, { body });
      load();
      return true;
    } catch (err) {
      setActionError(errorText(err));
      return false;
    }
  }

  async function remove(message: Message) {
    setActionError("");
    try {
      await api.del(`/orgs/${orgId}/rooms/${roomId}/messages/${message.id}`);
      setMessages((rows) => rows.filter((row) => row.id !== message.id));
      return true;
    } catch (err) {
      setActionError(errorText(err));
      return false;
    }
  }

  const online = members.filter((m) => m.active && m.presence === "online").length;
  const demo = !!access?.org.demo;

  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">{roomName || tr("Room")}</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="chat" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {canTranslate ? (
          <Button
            type="button"
            variant={translating ? "default" : "outline"}
            aria-pressed={translating}
            onClick={() => {
              setTranslateNote("");
              setTranslating((v) => !v);
            }}
          >
            {translating ? tr("Show originals") : tr("Translate to my language")}
          </Button>
        ) : null}
        <Button type="button" variant={showMembers ? "default" : "outline"} aria-pressed={showMembers} onClick={() => setShowMembers((v) => !v)}>
          {tr("Members ({n}, {online} online)", { n: members.length, online })}
        </Button>
      </div>
      {translateNote ? <Notice kind="error">{translateNote}</Notice> : null}
      {orgId && (state === "ready" || state === "empty") ? <AnnouncementsPanel orgId={orgId} roomId={roomId} canManage={canAnnounce} /> : null}
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          <ScreenBody state={state} error={error || orgError} emptyLabel={tr("No messages yet")} onRetry={load}>
            <ul className="space-y-4">
              {messages.map((message) => (
                <MessageItem
                  key={`${message.id}:${message.edited_at ?? ""}`}
                  message={message}
                  mine={!!selfId && message.author === selfId}
                  translation={translations[message.id]}
                  translating={translating}
                  demo={demo}
                  onSave={(body) => saveEdit(message, body)}
                  onDelete={() => remove(message)}
                  voice={
                    voiceOn && orgId && voice.notes[message.id] ? (
                      <RoomVoiceNote orgId={orgId} roomId={roomId} note={voice.notes[message.id]} mine={!!selfId && message.author === selfId} onChanged={voice.reload} />
                    ) : undefined
                  }
                />
              ))}
            </ul>
          </ScreenBody>
          {actionError ? <Notice kind="error">{actionError}</Notice> : null}
          {queued > 0 ? (
            <p role="status" className="mt-3 text-sm text-[color:var(--fb-v2-waiting)]">
              {tr("{n} message(s) waiting to send. They go out when you're back online.", { n: queued })}
            </p>
          ) : null}
          <form
            className="mt-4 flex flex-wrap gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!orgId || !canSendMessage(draft)) return;
              const body = draft;
              setActionError("");
              if (typeof navigator !== "undefined" && !navigator.onLine) {
                outbox.queue(orgId, roomId, body);
                setDraft("");
                setQueued(outbox.pending(roomId).length);
                return;
              }
              v2Client()
                .postMessage(orgId, roomId, body)
                .then(() => {
                  setDraft("");
                  load();
                })
                .catch((err) => {
                  if (isNetworkError(err)) {
                    outbox.queue(orgId, roomId, body);
                    setDraft("");
                    setQueued(outbox.pending(roomId).length);
                  } else {
                    setActionError(errorText(err));
                  }
                });
            }}
          >
            <input
              className="min-w-0 flex-1 rounded-[length:var(--fb-v2-radius)] border border-[color:var(--fb-v2-border)] bg-transparent px-3 py-2"
              value={draft}
              maxLength={8000}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={tr("Write a message. Use @name to mention someone.")}
              aria-label={tr("Write a message")}
            />
            <Button type="submit">{tr("Send")}</Button>
            {voiceOn && orgId ? (
              <RoomVoiceRecorder
                orgId={orgId}
                roomId={roomId}
                onSent={() => {
                  load();
                  voice.reload();
                }}
              />
            ) : null}
          </form>
          <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Attachments aren't available in chat yet. Share files in the Docs tab.")}</p>
        </div>
        {showMembers ? (
          <div className="lg:w-72">
            <RoomMembersPanel members={members} selfId={selfId} />
          </div>
        ) : null}
      </div>
    </section>
  );
}
