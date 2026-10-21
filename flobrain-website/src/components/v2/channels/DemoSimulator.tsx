"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { KIND_LABEL, type ChannelKind, type Conversation } from "./logic";

type Option = { id: string; kind: ChannelKind; label: string; demo: boolean; status?: string };

/** Demo only: pretend a message arrived, from a customer or from your own linked phone. */
export function DemoSimulator({ orgId, orgSlug, connections, canCustomers }: { orgId: string; orgSlug: string; connections: Option[]; canCustomers: boolean }) {
  const tr = useTr();
  const demo = connections.filter((c) => c.demo && (c.status ?? "active") === "active");
  const [connection, setConnection] = useState(demo[0]?.id ?? "");
  const [from, setFrom] = useState<"customer" | "me">(canCustomers ? "customer" : "me");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ reply?: string; conversation?: Conversation } | null>(null);
  const [error, setError] = useState("");
  const chosen = demo.find((c) => c.id === connection) ?? demo[0];
  if (!chosen) return null;
  const effectiveFrom = chosen.kind === "website" ? "customer" : from;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.post(`/orgs/${orgId}/channels/demo/simulate`, { connection: chosen.id, text, from: effectiveFrom }));
      setText("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const last = result?.conversation?.messages?.at(-1);
  return (
    <Section title={tr("Simulate an inbound message")}>
      <form className="rounded-xl border border-dashed border-[color:var(--fb-v2-border-strong)] p-4" onSubmit={send}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Demo only. Nothing is sent to WhatsApp or Telegram.")}</p>
        <div className="grid gap-x-4 md:grid-cols-2">
          <Field label={tr("Channel")}>
            <select className="v2-input w-full" value={chosen.id} onChange={(e) => setConnection(e.target.value)}>
              {demo.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label || tr(KIND_LABEL[c.kind])}
                </option>
              ))}
            </select>
          </Field>
          <Field label={tr("From")}>
            <select className="v2-input w-full" value={effectiveFrom} disabled={chosen.kind === "website"} onChange={(e) => setFrom(e.target.value as "customer" | "me")}>
              {canCustomers ? <option value="customer">{tr("A customer")}</option> : null}
              {chosen.kind !== "website" ? <option value="me">{tr("Me, from my linked phone")}</option> : null}
            </select>
          </Field>
        </div>
        <Field label={tr("Message")}>
          <input className="v2-input w-full" required maxLength={2000} value={text} placeholder={tr("For example: How much is the Team plan?")} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Button type="submit" disabled={busy || !text.trim()}>
          {tr("Simulate")}
        </Button>
        {error ? <Notice kind="error">{error}</Notice> : null}
        {result?.reply ? (
          <div className="mt-3 rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-sm" role="status">
            <p className="mb-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Your buddy would reply:")}</p>
            <p className="whitespace-pre-wrap">{result.reply}</p>
          </div>
        ) : null}
        {result?.conversation ? (
          <div className="mt-3 text-sm" role="status">
            <p>
              {last?.status === "draft"
                ? tr("The buddy wrote a draft. It waits for approval in Customers.")
                : result.conversation.status === "waiting_human"
                  ? tr("The buddy handed this customer to a person.")
                  : tr("The buddy answered.")}
            </p>
            <Link className="underline" href={`/w/${orgSlug}/customers?c=${result.conversation.id}`}>
              {tr("Open in Customers")}
            </Link>
          </div>
        ) : null}
      </form>
    </Section>
  );
}
