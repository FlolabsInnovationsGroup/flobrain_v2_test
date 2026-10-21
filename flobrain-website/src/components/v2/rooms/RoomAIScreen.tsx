"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { roomTime, roomTitle } from "@/components/v2/rooms/format";
import { RoomTabs } from "@/components/v2/screens/RoomTabs";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText } from "@/lib/v2/api";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";

type Citation = { n: number; source_type: string; source_id: string; room?: string; title: string; excerpt: string };
type ThreadMessage = { id: number; role: "user" | "assistant"; text: string; sources?: Citation[]; created_at?: string };
type Thread = { id: number; title: string; updated_at?: string; messages?: ThreadMessage[] };
type Models = {
  direct?: { id: string; name: string }[];
  default?: string | null;
  providers?: { credential_id: string; provider: string; label: string; last4: string }[];
};
type SendResult = Thread & { usage?: { model?: string }; sources_state?: string; citations?: Citation[] };

/** Plain words for a failed send: budget, private-only AI, switched off, or what the server said. */
function sendError(err: unknown, tr: (s: string) => string): string {
  const e = apiError(err);
  if (e.status === 429 && (e.code === "budget_exceeded" || e.details.toLowerCase().includes("budget"))) {
    return tr("Your organization has used its AI budget for now. Ask an admin to raise the limit, or try again later.");
  }
  if (e.status === 429) return tr("You're sending too fast. Wait a minute and try again.");
  if (e.status === 409 && e.code === "private_only") {
    return tr("Your organization only allows self-hosted AI, and this model isn't one. Ask an admin to set up a self-hosted model.");
  }
  if (e.status === 501) return tr("The AI model isn't set up yet. An admin can connect one in AI settings.");
  if (e.status === 502) return tr("The AI model didn't answer. Try again.");
  return errorText(err);
}

function Sources({ orgSlug, citations }: { orgSlug: string; citations: Citation[] }) {
  const tr = useTr();
  if (!citations.length) return null;
  return (
    <div className="mt-3">
      <h3 className="mb-1 text-xs font-semibold">{tr("Sources")}</h3>
      <ol className="space-y-1 text-sm">
        {citations.map((c) => (
          <li key={`${c.n}-${c.source_id}`} className="flex gap-2">
            <span className="text-[color:var(--fb-v2-text-muted)]">[{c.n}]</span>
            <span className="min-w-0">
              {c.room ? (
                <Link
                  className="font-medium hover:underline"
                  href={c.source_type === "doc" ? `/w/${orgSlug}/rooms/${c.room}/docs` : `/w/${orgSlug}/rooms/${c.room}`}
                >
                  {c.title}
                </Link>
              ) : (
                <span className="font-medium">{c.title}</span>
              )}
              <span className="block truncate text-[color:var(--fb-v2-text-muted)]">{c.excerpt}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Private AI threads in a room: only you see your threads. Answers can use the room's sources you can read. */
export function RoomAIScreen({ orgSlug, roomId }: { orgSlug: string; roomId: string }) {
  const tr = useTr();
  const { access, orgId } = useAccess();
  const [roomName, setRoomName] = useState("");
  const [threads, setThreads] = useState<Thread[]>([]);
  const [loadState, setLoadState] = useState<ScreenState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [current, setCurrent] = useState<Thread | null>(null);
  const [models, setModels] = useState<Models>({});
  const [choice, setChoice] = useState("");
  const [keyModel, setKeyModel] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastModel, setLastModel] = useState("");
  const [sourcesNote, setSourcesNote] = useState("");

  const allowed = flag(access, "room_ai") && has(access, "ai.use");

  const fetchThreads = useCallback(() => {
    if (!orgId) return;
    api
      .get<Record<string, unknown>>(`/orgs/${orgId}/rooms/${roomId}`)
      .then((room) => setRoomName(roomTitle({ name: String(room.name ?? ""), kind: String(room.kind ?? ""), other_name: room.other_name as string | undefined })))
      .catch(() => undefined);
    api
      .get<Thread[]>(`/orgs/${orgId}/rooms/${roomId}/ai/threads`)
      .then((rows) => {
        setThreads(rows);
        setLoadState("ready");
      })
      .catch((err) => {
        const e = apiError(err);
        setLoadError(e.details || null);
        setLoadState(screenStateFromHttp(e.status || 500));
      });
    api
      .get<Models>(`/orgs/${orgId}/ai/models`)
      .then(setModels)
      .catch(() => setModels({}));
  }, [orgId, roomId]);

  useEffect(() => {
    if (allowed) fetchThreads();
  }, [allowed, fetchThreads]);

  const open = useCallback(
    (id: number) => {
      if (!orgId) return;
      setError("");
      setSourcesNote("");
      setLastModel("");
      api
        .get<Thread>(`/orgs/${orgId}/ai/threads/${id}`)
        .then(setCurrent)
        .catch((err) => setError(errorText(err)));
    },
    [orgId],
  );

  async function startThread() {
    if (!orgId) return;
    setError("");
    try {
      const thread = await api.post<Thread>(`/orgs/${orgId}/rooms/${roomId}/ai/threads`, {});
      setThreads((rows) => [thread, ...rows]);
      setCurrent(thread);
      setLastModel("");
      setSourcesNote("");
    } catch (err) {
      setError(sendError(err, tr));
    }
  }

  const options = [
    ...(models.direct ?? []).map((m) => ({ value: `m:${m.name}`, label: m.name })),
    ...(models.providers ?? []).map((k) => ({ value: `k:${k.credential_id}`, label: tr("Your key: {label} (…{last4})", { label: k.label || k.provider, last4: k.last4 }) })),
  ];
  const picked = choice || (models.default ? `m:${models.default}` : options[0]?.value ?? "");

  async function submit() {
    if (!orgId || !draft.trim() || busy) return;
    let thread = current;
    setBusy(true);
    setError("");
    try {
      if (!thread) {
        thread = await api.post<Thread>(`/orgs/${orgId}/rooms/${roomId}/ai/threads`, {});
        setThreads((rows) => [thread as Thread, ...rows]);
      }
      const body: Record<string, string> = { text: draft.trim() };
      if (options.length > 1 || picked.startsWith("k:")) {
        if (picked.startsWith("m:")) body.model = picked.slice(2);
        if (picked.startsWith("k:")) {
          body.credential_id = picked.slice(2);
          body.model = keyModel.trim();
        }
      }
      const result = await api.post<SendResult>(`/orgs/${orgId}/ai/threads/${thread.id}/send`, body);
      setCurrent(result);
      setThreads((rows) => [{ id: result.id, title: result.title, updated_at: result.updated_at }, ...rows.filter((r) => r.id !== result.id)]);
      setDraft("");
      setLastModel(result.usage?.model ?? "");
      setSourcesNote(
        result.sources_state === "disabled"
          ? tr("Answers don't use room sources because memory search is off for your organization.")
          : result.sources_state === "none"
            ? tr("No room sources matched this question, so the answer uses your words only.")
            : "",
      );
    } catch (err) {
      if (thread) setCurrent((prev) => prev ?? thread);
      setError(sendError(err, tr));
    } finally {
      setBusy(false);
    }
  }

  if (access && !allowed) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold">{tr("Room AI")}</h1>
        <RoomTabs orgSlug={orgSlug} roomId={roomId} current="ai" />
        <Notice>
          {!flag(access, "room_ai")
            ? tr("Room AI is switched off for your organization. An admin can turn it on.")
            : tr("You don't have permission to use AI. Ask an admin for access.")}
        </Notice>
      </section>
    );
  }

  const messages = current?.messages ?? [];
  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">{roomName ? tr("AI in {room}", { room: roomName }) : tr("Room AI")}</h1>
      <RoomTabs orgSlug={orgSlug} roomId={roomId} current="ai" />
      <p className="mb-4 max-w-2xl text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Your threads here are private. Nobody else in the room, admins included, can read them. Answers can use this room's messages and documents that you can open.")}
      </p>
      <ScreenBody state={access ? loadState : "loading"} error={loadError} onRetry={fetchThreads}>
        <div className="flex flex-col gap-4 lg:flex-row">
          <aside className="lg:w-64" aria-label={tr("Your threads")}>
            <Button type="button" className="mb-3 w-full" onClick={startThread}>
              {tr("New thread")}
            </Button>
            {threads.length === 0 ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No threads yet. Ask your first question.")}</p> : null}
            <ul className="space-y-1">
              {threads.map((thread) => (
                <li key={thread.id}>
                  <button
                    type="button"
                    onClick={() => open(thread.id)}
                    aria-current={current?.id === thread.id ? "true" : undefined}
                    className={`w-full rounded-lg px-2 py-1.5 text-start text-sm hover:bg-[color:var(--fb-v2-border)] ${current?.id === thread.id ? "bg-[color:var(--fb-v2-border)] font-medium" : ""}`}
                  >
                    <span className="block truncate">{thread.title === "New Chat" ? tr("New thread") : thread.title}</span>
                    {thread.updated_at ? <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">{roomTime(thread.updated_at, tr)}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <div className="min-w-0 flex-1 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
            {messages.length === 0 ? (
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Ask about this room: decisions, deadlines, who owns what.")}</p>
            ) : (
              <ul className="space-y-4">
                {messages.map((m, i) => (
                  <li key={m.id ?? i} className={m.role === "user" ? "flex justify-end" : ""}>
                    <div className={m.role === "user" ? "max-w-[85%] rounded-xl bg-[color:var(--fb-v2-border)] px-3 py-2" : "max-w-full"}>
                      <p className="mb-1 text-xs text-[color:var(--fb-v2-text-muted)]">
                        {m.role === "user" ? tr("You") : tr("FloBrain")}
                        {m.created_at ? ` · ${roomTime(m.created_at, tr)}` : ""}
                      </p>
                      <p className="whitespace-pre-wrap break-words">{m.text}</p>
                      {m.role === "assistant" ? <Sources orgSlug={orgSlug} citations={m.sources ?? []} /> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {busy ? <Notice>{tr("Thinking…")}</Notice> : null}
            {lastModel ? (
              <p className="mt-3 text-xs text-[color:var(--fb-v2-text-muted)]">
                {lastModel === "flobrain-demo" ? <Badge>{tr("Demo model")}</Badge> : tr("Model: {model}", { model: lastModel })}
              </p>
            ) : null}
            {sourcesNote ? <Notice>{sourcesNote}</Notice> : null}
            {error ? (
              <div className="flex flex-wrap items-center gap-2">
                <Notice kind="error">{error}</Notice>
                {draft.trim() ? (
                  <Button type="button" variant="outline" onClick={submit} disabled={busy}>
                    {tr("Retry")}
                  </Button>
                ) : null}
              </div>
            ) : null}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
              className="mt-4"
            >
              {options.length > 1 ? (
                <div className="mb-2 flex flex-wrap gap-2">
                  <Field label={tr("Model")}>
                    <select className="v2-input py-1" value={picked} onChange={(event) => setChoice(event.target.value)}>
                      {options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {picked.startsWith("k:") ? (
                    <Field label={tr("Model name for your key")}>
                      <input className="v2-input py-1" value={keyModel} onChange={(event) => setKeyModel(event.target.value)} placeholder="gpt-4o-mini" />
                    </Field>
                  ) : null}
                </div>
              ) : null}
              <div className="flex gap-2">
                <input
                  className="v2-input"
                  value={draft}
                  maxLength={8000}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder={tr("Ask a question about this room")}
                  aria-label={tr("Question")}
                />
                <Button type="submit" disabled={busy || !draft.trim() || (picked.startsWith("k:") && !keyModel.trim())}>
                  {busy ? tr("Asking…") : tr("Ask")}
                </Button>
              </div>
            </form>
          </div>
        </div>
      </ScreenBody>
    </section>
  );
}
