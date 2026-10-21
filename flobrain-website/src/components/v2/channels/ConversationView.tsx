"use client";

import { useState } from "react";

import { MemberPicker } from "@/components/v2/rooms/MemberPicker";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { DELIVERY_LABEL, KIND_LABEL, REASON_LABEL, STATUS_LABEL, conversationTone, type Conversation, type CustomerMessage } from "./logic";

type Room = { id: string; name: string };

function Bubble({ m, canReply, onDecide }: { m: CustomerMessage; canReply: boolean; onDecide: (m: CustomerMessage, decision: "approve" | "reject", text?: string) => void }) {
  const tr = useTr();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.text);
  if (m.status === "rejected") return null;
  const fromCustomer = m.role === "customer";
  const draft = m.status === "draft";
  const who =
    m.role === "customer"
      ? tr("Customer")
      : m.role === "buddy"
        ? tr("Customer buddy")
        : m.role === "staff"
          ? m.author?.name ?? tr("Team")
          : tr("Automatic message");
  return (
    <li className={`flex ${fromCustomer ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
          draft
            ? "border-2 border-dashed border-[color:var(--fb-v2-waiting)] bg-[color:var(--fb-v2-surface)]"
            : fromCustomer
              ? "bg-[color:var(--fb-v2-raised)]"
              : "bg-[color:var(--fb-v2-accent-soft)]"
        }`}
      >
        <p className="mb-1 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
          <span className="font-medium text-[color:var(--fb-v2-text)]">{who}</span>
          <span>{when(m.created_at)}</span>
          {draft ? <Badge tone="waiting">{tr("Draft waiting for approval")}</Badge> : null}
          {m.status === "failed" ? <Badge tone="bad">{tr("Not sent")}</Badge> : null}
        </p>
        {editing ? (
          <textarea className="v2-input min-h-24 w-full" value={text} maxLength={4000} aria-label={tr("Edit the reply")} onChange={(e) => setText(e.target.value)} />
        ) : (
          <p className="whitespace-pre-wrap">{m.text}</p>
        )}
        {m.media?.type === "voice" ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Voice note (not transcribed yet)")}</p> : null}
        {m.citations?.length ? (
          <ul className="mt-2 space-y-1 border-t border-[color:var(--fb-v2-border)] pt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
            {m.citations.map((c) => (
              <li key={c.n}>
                [{c.n}] {c.title}
              </li>
            ))}
          </ul>
        ) : null}
        {m.status === "failed" && m.delivery_error ? (
          <p className="mt-1 text-xs text-[color:var(--fb-v2-error)]">{tr(DELIVERY_LABEL[m.delivery_error] ?? "Not sent: the channel did not accept it.")}</p>
        ) : null}
        {m.approved_by && m.role === "buddy" && !draft ? (
          <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Approved by {name}", { name: m.approved_by.name })}</p>
        ) : null}
        {draft && canReply ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="waiting" onClick={() => onDecide(m, "approve", editing && text !== m.text ? text : undefined)}>
              {editing ? tr("Send edited reply") : tr("Approve and send")}
            </Button>
            {!editing ? (
              <Button variant="outline" onClick={() => setEditing(true)}>
                {tr("Edit")}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => onDecide(m, "reject")}>
              {tr("Discard")}
            </Button>
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function ConversationView({
  orgId,
  conversation,
  canReply,
  selfId,
  rooms,
  onChange,
}: {
  orgId: string;
  conversation: Conversation;
  canReply: boolean;
  selfId: string;
  rooms: Room[];
  onChange: (c: Conversation) => void;
}) {
  const tr = useTr();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [assigning, setAssigning] = useState(false);
  const url = `/orgs/${orgId}/customers/conversations/${conversation.id}`;

  async function run(path: string, body: unknown, ok: string) {
    setBusy(true);
    setNotice(null);
    try {
      const next = await api.post<Conversation>(`${url}${path}`, body);
      onChange(next);
      if (next.delivered === false) {
        setNotice({ kind: "error", text: tr(DELIVERY_LABEL[next.error ?? ""] ?? "Not sent: the channel did not accept it.") });
      } else {
        setNotice({ kind: "ok", text: ok });
      }
      return true;
    } catch (err) {
      setNotice({ kind: "error", text: errorText(err) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  const decide = (m: CustomerMessage, decision: "approve" | "reject", text?: string) =>
    run(`/messages/${m.id}/${decision}`, text ? { text } : {}, decision === "approve" ? tr("Sent to the customer.") : tr("Draft discarded."));

  const human = conversation.mode === "human";
  return (
    <section aria-label={tr("Conversation")} className="flex min-h-0 flex-col rounded-xl bg-[color:var(--fb-v2-surface)]">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--fb-v2-border)] p-4">
        <div>
          <h2 className="text-lg font-semibold">{conversation.customer_name}</h2>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr(KIND_LABEL[conversation.channel])}
            {conversation.contact ? ` · ${conversation.contact}` : ""}
            {conversation.demo ? ` · ${tr("Demo")}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge tone={conversationTone({ status: conversation.status, drafts: conversation.messages?.filter((m) => m.status === "draft").length })}>
              {tr(STATUS_LABEL[conversation.status])}
            </Badge>
            <Badge tone={human ? "accent" : "neutral"}>{human ? tr("A person is answering") : tr("The buddy is answering")}</Badge>
            {conversation.escalation_reason ? <Badge>{tr(REASON_LABEL[conversation.escalation_reason] ?? "Handed to a person")}</Badge> : null}
          </div>
          <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
            {conversation.assignee ? tr("Assigned to {name}", { name: conversation.assignee.name }) : tr("No one is assigned")}
            {conversation.assigned_room_name ? ` · ${tr("Room: {name}", { name: conversation.assigned_room_name })}` : ""}
          </p>
        </div>
        {canReply ? (
          <div className="flex flex-wrap gap-2">
            {human ? (
              <Button variant="outline" disabled={busy} onClick={() => run("/handback", {}, tr("The buddy answers again."))}>
                {tr("Hand back to buddy")}
              </Button>
            ) : (
              <Button variant="outline" disabled={busy} onClick={() => run("/takeover", {}, tr("You took over. The buddy stays quiet."))}>
                {tr("Take over")}
              </Button>
            )}
            {conversation.status !== "resolved" ? (
              <Button variant="outline" disabled={busy} onClick={() => run("/resolve", {}, tr("Marked resolved."))}>
                {tr("Resolve")}
              </Button>
            ) : null}
            <Button variant="ghost" aria-expanded={assigning} onClick={() => setAssigning((v) => !v)}>
              {tr("Assign")}
            </Button>
          </div>
        ) : null}
      </header>
      {assigning && canReply ? (
        <div className="grid gap-4 border-b border-[color:var(--fb-v2-border)] p-4 md:grid-cols-2">
          <div>
            <Button variant="outline" className="mb-2" onClick={() => run("/assign", { assignee: selfId }, tr("Assigned to you."))}>
              {tr("Assign to me")}
            </Button>
            <MemberPicker orgId={orgId} label={tr("Assign to someone")} onPick={(p) => run("/assign", { assignee: p.id }, tr("Assigned to {name}.", { name: p.name }))} />
          </div>
          <label className="text-sm">
            <span className="mb-1 block font-medium">{tr("Room for this conversation")}</span>
            <select
              className="v2-input w-full"
              value={conversation.assigned_room ?? ""}
              onChange={(e) => run("/assign", { room: e.target.value || null }, tr("Room changed."))}
            >
              <option value="">{tr("No room")}</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
      <ul className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
        {(conversation.messages ?? []).map((m) => (
          <Bubble key={`${m.id}:${m.status}`} m={m} canReply={canReply} onDecide={decide} />
        ))}
      </ul>
      {notice ? (
        <div className="px-4">
          <Notice kind={notice.kind}>{notice.text}</Notice>
        </div>
      ) : null}
      {canReply ? (
        <form
          className="flex flex-col gap-2 border-t border-[color:var(--fb-v2-border)] p-4 sm:flex-row sm:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!reply.trim()) return;
            if (await run("/reply", { text: reply.trim() }, tr("Sent to the customer."))) setReply("");
          }}
        >
          <label className="flex-1 text-sm">
            <span className="sr-only">{tr("Your reply")}</span>
            <textarea
              className="v2-input min-h-20 w-full"
              placeholder={tr("Write a reply. Sending it takes over from the buddy.")}
              maxLength={4000}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
            />
          </label>
          <Button type="submit" disabled={busy || !reply.trim()}>
            {tr("Send")}
          </Button>
        </form>
      ) : (
        <p className="p-4 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("You can read this conversation but not reply.")}</p>
      )}
    </section>
  );
}
