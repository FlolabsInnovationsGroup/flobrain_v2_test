"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ConversationView } from "@/components/v2/channels/ConversationView";
import { KIND_LABEL, REASON_LABEL, STATUS_LABEL, conversationTone, sortInbox, type Conversation } from "@/components/v2/channels/logic";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Badge, Notice, PageHeader, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Filter = "" | "drafts" | "waiting_human" | "open" | "resolved";

export default function CustomersPage() {
  return (
    <Suspense>
      <Inbox />
    </Suspense>
  );
}

function Inbox() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const params = useSearchParams();
  const [filter, setFilter] = useState<Filter>("");
  // A notification link opens one conversation: /customers?c=<id>.
  const [selected, setSelected] = useState<string | null>(params.get("c"));
  const [current, setCurrent] = useState<Conversation | null>(null);
  const [loadError, setLoadError] = useState("");
  const path = filter ? `/customers/conversations?status=${filter}` : "/customers/conversations";
  const { data, state, error, reload } = useOrgData<Conversation[]>(orgId, path, { list: true });
  const { data: roomData } = useOrgData<{ id: string; name: string }[]>(orgId, "/rooms");
  const rows = sortInbox(rowsOf<Conversation>(data));
  const canReply = has(access, "customers.reply");

  useEffect(() => {
    if (!orgId || !selected) return;
    let cancelled = false;
    api
      .get<Conversation>(`/orgs/${orgId}/customers/conversations/${selected}`)
      .then((c) => {
        if (!cancelled) setCurrent(c);
      })
      .catch((err) => {
        if (cancelled) return;
        setCurrent(null);
        setLoadError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [orgId, selected]);

  const open = (id: string) => {
    setLoadError("");
    setSelected(id);
  };
  const shown = current && current.id === selected ? current : null;

  const filters: { key: Filter; label: string }[] = [
    { key: "", label: tr("All") },
    { key: "drafts", label: tr("Drafts to approve") },
    { key: "waiting_human", label: tr("Waiting for a person") },
    { key: "open", label: tr("state|Open") },
    { key: "resolved", label: tr("Resolved") },
  ];

  return (
    <div className="max-w-7xl">
      <PageHeader
        title={tr("Customers")}
        intro={tr("Conversations from your website chat, WhatsApp and Telegram. The customer buddy answers from public knowledge only and hands off to a person when it is not sure.")}
      />
      <div role="tablist" aria-label={tr("Filter conversations")} className="mb-4 flex flex-wrap gap-2">
        {filters.map((f) => (
          <button
            key={f.key || "all"}
            role="tab"
            aria-selected={filter === f.key}
            className={`rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] ${
              filter === f.key ? "bg-[color:var(--fb-v2-accent)] text-white" : "hover:bg-[color:var(--fb-v2-border)]"
            }`}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className={selected ? "hidden lg:block" : ""}>
          <ScreenBody state={state} error={error} emptyLabel={tr("No conversations here yet.")} onRetry={reload}>
            <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
              {rows.map((c) => (
                <li key={c.id}>
                  <button
                    className={`flex w-full flex-col gap-1 px-4 py-3 text-start hover:bg-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] ${
                      selected === c.id ? "bg-[color:var(--fb-v2-raised)]" : ""
                    }`}
                    aria-current={selected === c.id ? "true" : undefined}
                    onClick={() => open(c.id)}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium">{c.customer_name}</span>
                      <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{when(c.last_message_at)}</span>
                    </span>
                    <span className="line-clamp-2 text-sm text-[color:var(--fb-v2-text-muted)]">{c.preview}</span>
                    <span className="flex flex-wrap gap-1">
                      <Badge>{tr(KIND_LABEL[c.channel])}</Badge>
                      {c.drafts ? (
                        <Badge tone="waiting">{tr("{n} drafts to approve", { n: c.drafts })}</Badge>
                      ) : (
                        <Badge tone={conversationTone(c)}>{tr(STATUS_LABEL[c.status])}</Badge>
                      )}
                      {c.status === "waiting_human" && c.escalation_reason ? <Badge>{tr(REASON_LABEL[c.escalation_reason] ?? "Handed to a person")}</Badge> : null}
                      {c.demo ? <Badge>{tr("Demo")}</Badge> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </ScreenBody>
        </div>
        <div className={selected ? "" : "hidden lg:block"}>
          {selected ? (
            <button className="mb-2 text-sm underline lg:hidden" onClick={() => { setSelected(null); setCurrent(null); }}>
              {tr("Back to the list")}
            </button>
          ) : null}
          {loadError ? <Notice kind="error">{loadError}</Notice> : null}
          {shown && orgId && access ? (
            <ConversationView
              orgId={orgId}
              conversation={shown}
              canReply={canReply}
              selfId={access.user_id}
              rooms={rowsOf<{ id: string; name: string }>(roomData)}
              onChange={(next) => {
                setCurrent(next);
                reload();
              }}
            />
          ) : !selected ? (
            <p className="rounded-xl bg-[color:var(--fb-v2-surface)] p-6 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Pick a conversation to read it.")}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
