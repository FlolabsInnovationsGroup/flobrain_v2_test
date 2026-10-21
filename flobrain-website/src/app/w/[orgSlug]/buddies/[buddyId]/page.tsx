"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Feedback, useThreadFeedback } from "@/components/v2/crew/Feedback";
import { Badge, Notice, PageHeader } from "@/components/v2/ui/kit";
import { BuddyVoiceInput } from "@/components/v2/voice/BuddyVoiceInput";
import { useTr } from "@/i18n/phrases";
import { flag } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Buddy = {
  id: string;
  name: string;
  description: string;
  mine: boolean;
  builtin: boolean;
  visibility: string;
  share_status: string;
  preset_prompts: { label: string; prompt: string }[];
};
type Message = { id?: number; role: "user" | "assistant" | "external"; text: string };
type Citation = { n: number; title: string; excerpt: string; room?: string };
type Proposal = { id: string; summary: string };
type Thread = {
  id: number;
  title: string;
  messages: Message[];
  citations?: Citation[];
  proposals?: Proposal[];
  external_calls?: { id: string; tool: string; server?: { name?: string } }[];
  usage?: { model?: string; downgraded?: boolean };
};

export default function BuddyChatPage() {
  const { orgSlug, buddyId } = useParams<{ orgSlug: string; buddyId: string }>();
  const { orgId, access } = useAccess();
  const tr = useTr();
  const { data: buddy, state, error, reload } = useOrgData<Buddy>(orgId, `/buddies/${buddyId}`);
  const [threads, setThreads] = useState<{ id: number; title: string }[]>([]);
  const [thread, setThread] = useState<Thread | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const rateable = flag(access, "flo_router");
  const { ratings } = useThreadFeedback(rateable ? orgId : null, thread?.id ?? null);

  const loadThreads = useCallback(() => {
    if (!orgId) return;
    api
      .get(`/orgs/${orgId}/buddies/${buddyId}/threads`)
      .then((value) => setThreads(rowsOf(value)))
      .catch(() => setThreads([]));
  }, [orgId, buddyId]);

  useEffect(loadThreads, [loadThreads]);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [thread]);

  async function open(id: number) {
    setThread(await api.get<Thread>(`/orgs/${orgId}/buddies/threads/${id}`));
  }

  async function send(text: string) {
    if (!text.trim() || !orgId) return;
    setBusy(true);
    setMessage(null);
    try {
      let current = thread;
      if (!current) {
        current = await api.post<Thread>(`/orgs/${orgId}/buddies/${buddyId}/threads`, {});
        loadThreads();
      }
      setThread({ ...current, messages: [...current.messages, { role: "user", text }] });
      setDraft("");
      setThread(await api.post<Thread>(`/orgs/${orgId}/buddies/threads/${current.id}/send`, { text }));
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function share(target: "team" | "org" | "private") {
    setMessage(null);
    try {
      const res = await api.post<Buddy>(`/orgs/${orgId}/buddies/${buddyId}/share`, { target });
      setMessage({
        kind: "ok",
        text: res.share_status === "pending" ? tr("Sent for approval. An admin decides.") : target === "private" ? tr("Only you can use it now.") : tr("Shared."),
      });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <ScreenBody state={state} error={error} onRetry={reload}>
      {buddy ? (
        <div className="grid max-w-6xl gap-6 lg:grid-cols-[14rem_1fr]">
          <aside>
            <Link href={`/w/${orgSlug}/buddies`} className="text-sm text-[color:var(--fb-v2-text-muted)] hover:underline">
              {tr("All buddies")}
            </Link>
            <Button className="mt-3 w-full" variant="outline" onClick={() => setThread(null)}>
              {tr("New conversation")}
            </Button>
            <ul className="mt-3 space-y-1 text-sm">
              {threads.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => open(t.id)}
                    className="w-full truncate rounded-lg px-2 py-1 text-start hover:bg-[color:var(--fb-v2-border)]"
                  >
                    {t.title}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <div className="min-w-0">
            <PageHeader
              title={buddy.name}
              intro={buddy.description}
              action={
                buddy.mine && !buddy.builtin ? (
                  <div className="flex flex-wrap items-center gap-2">
                    {buddy.share_status === "pending" ? <Badge tone="waiting">{tr("Waiting for approval")}</Badge> : null}
                    <select
                      className="v2-input w-auto"
                      aria-label={tr("Who can use it")}
                      value={buddy.share_status === "pending" ? "" : buddy.visibility}
                      onChange={(e) => share(e.target.value as "team" | "org" | "private")}
                    >
                      <option value="" disabled>
                        {tr("Choose…")}
                      </option>
                      <option value="private">{tr("Only me")}</option>
                      <option value="org">{tr("Share with everyone")}</option>
                    </select>
                  </div>
                ) : null
              }
            />
            {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
            <div className="min-h-64 space-y-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              {!thread || thread.messages.length === 0 ? (
                <div>
                  <p className="text-[color:var(--fb-v2-text-muted)]">{tr("Start with one of these, or write your own.")}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {buddy.preset_prompts.map((p) => (
                      <Button key={p.label} variant="outline" onClick={() => send(p.prompt)} disabled={busy}>
                        {p.label}
                      </Button>
                    ))}
                    <Button variant="outline" onClick={() => send("Create a task to update the store screenshots")} disabled={busy}>
                      {tr("Propose a task")}
                    </Button>
                  </div>
                </div>
              ) : (
                thread.messages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "ms-auto max-w-[80%] text-end" : "max-w-[85%]"}>
                    <p
                      className={
                        m.role === "user"
                          ? "inline-block rounded-xl bg-[color:var(--fb-v2-accent)] px-3 py-2 text-white"
                          : m.role === "external"
                            ? "whitespace-pre-wrap border-s-2 border-[color:var(--fb-v2-waiting)] ps-3 text-sm text-[color:var(--fb-v2-text-muted)]"
                            : "whitespace-pre-wrap"
                      }
                    >
                      {m.text}
                    </p>
                    {m.role === "assistant" && m.id && orgId && rateable ? <Feedback orgId={orgId} messageId={m.id} initial={ratings[m.id] ?? null} /> : null}
                  </div>
                ))
              )}
              {thread?.usage?.downgraded ? (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("An AI budget is used up, so this answer came from a cheaper model ({model}).", { model: thread.usage.model ?? "" })}
                </p>
              ) : null}
              {thread?.proposals?.length ? (
                <div className="rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]">
                  <p className="text-sm font-medium">{tr("Waiting for your approval")}</p>
                  <ul className="mt-1 list-disc ps-5 text-sm">
                    {thread.proposals.map((p) => (
                      <li key={p.id}>{p.summary}</li>
                    ))}
                  </ul>
                  <Link href={`/w/${orgSlug}/approvals`} className="mt-2 inline-block text-sm font-medium underline">
                    {tr("Review in Approvals")}
                  </Link>
                </div>
              ) : null}
              {thread?.external_calls?.length ? (
                <div className="rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]">
                  <p className="text-sm font-medium">{tr("An outside agent call is waiting for your approval")}</p>
                  <ul className="mt-1 list-disc ps-5 text-sm">
                    {thread.external_calls.map((c) => (
                      <li key={c.id}>{c.server?.name ? `${c.server.name}: ${c.tool}` : c.tool}</li>
                    ))}
                  </ul>
                  <Link href={`/w/${orgSlug}/settings/external-agents`} className="mt-2 inline-block text-sm font-medium underline">
                    {tr("Review it in External agents")}
                  </Link>
                </div>
              ) : null}
              {thread?.citations?.length ? (
                <details className="text-sm">
                  <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Sources ({n})", { n: thread.citations.length })}</summary>
                  <ol className="mt-2 space-y-1">
                    {thread.citations.map((c) => (
                      <li key={c.n}>
                        [{c.n}] {c.title}: <span className="text-[color:var(--fb-v2-text-muted)]">{c.excerpt}</span>
                      </li>
                    ))}
                  </ol>
                </details>
              ) : null}
              <div ref={end} />
            </div>
            <form
              className="mt-3 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                send(draft);
              }}
            >
              <input className="v2-input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={tr("Message {name}", { name: buddy.name })} aria-label={tr("Message")} />
              <Button type="submit" disabled={busy || !draft.trim()}>
                {busy ? tr("Thinking…") : tr("Send")}
              </Button>
              {flag(access, "voice_notes") && orgId ? (
                <BuddyVoiceInput orgId={orgId} disabled={busy} onTranscript={(text) => setDraft((d) => (d.trim() ? `${d.trim()} ${text}` : text))} />
              ) : null}
            </form>
          </div>
        </div>
      ) : null}
    </ScreenBody>
  );
}
