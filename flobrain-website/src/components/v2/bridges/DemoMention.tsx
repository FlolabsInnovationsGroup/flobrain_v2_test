"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { DEMO_MENTION, cardView, platformName, type Card, type Platform, type SimulateResult, type Workspace } from "./logic";

/** The approval message as Slack or Teams would show it, with working buttons (demo). */
export function ApprovalPreview({ orgId, card, onDecided }: { orgId: string; card: Card; onDecided: (card: Card) => void }) {
  const tr = useTr();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const view = cardView(card);
  const waiting = card.status === "waiting" && card.proposal.status === "proposed";
  const done = card.proposal.status === "executed";

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ card: Card }>(`/orgs/${orgId}/bridges/demo/decide`, { card: card.id, decision });
      onDecided(res.card);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const edge = waiting ? "var(--fb-v2-waiting)" : done ? "var(--fb-v2-success)" : "var(--fb-v2-border-strong)";
  return (
    <div className="rounded-lg border-s-4 bg-[color:var(--fb-v2-raised)] p-3 text-sm" style={{ borderInlineStartColor: edge }} role="group" aria-label={tr("Approval message")}>
      <p className="mb-1 text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Direct message from FloBrain in {platform}", { platform: platformName(card.platform) })}
      </p>
      <p className="font-semibold">{view.title}</p>
      <p className="whitespace-pre-wrap">{view.summary}</p>
      {view.note ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{view.note}</p> : null}
      {waiting ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="waiting" disabled={busy} onClick={() => void decide("approve")}>
            {tr("Approve")}
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => void decide("reject")}>
            {tr("Reject")}
          </Button>
        </div>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </div>
  );
}

/** Demo only: a Slack mention (or Teams message) from you, run end to end with nothing sent anywhere. */
export function DemoMention({ orgId, workspaces }: { orgId: string; workspaces: Workspace[] }) {
  const tr = useTr();
  const available = workspaces.filter((w) => w.demo && w.status === "active");
  const [platform, setPlatform] = useState<Platform>(available.find((w) => w.platform === "slack") ? "slack" : "teams");
  const [text, setText] = useState(DEMO_MENTION);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SimulateResult | null>(null);
  if (!available.length) return null;
  const chosen = available.find((w) => w.platform === platform) ? platform : available[0].platform;

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.post<SimulateResult>(`/orgs/${orgId}/bridges/demo/simulate`, { platform: chosen, text }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function replaceCard(card: Card) {
    setResult((r) => (r ? { ...r, cards: r.cards.map((c) => (c.id === card.id ? card : c)) } : r));
  }

  return (
    <Section title={chosen === "slack" ? tr("Simulate a Slack mention") : tr("Simulate a Teams message")}>
      <form className="rounded-xl border border-dashed border-[color:var(--fb-v2-border-strong)] p-4" onSubmit={run}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Demo only. FloBrain runs the whole flow as you, but nothing is sent to Slack or Microsoft.")}
        </p>
        <div className="grid gap-x-4 md:grid-cols-[12rem_1fr]">
          <Field label={tr("Where")}>
            <select className="v2-input w-full" value={chosen} onChange={(e) => setPlatform(e.target.value as Platform)}>
              {available.map((w) => (
                <option key={w.id} value={w.platform}>
                  {platformName(w.platform)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={chosen === "slack" ? tr("Your message after @FloBrain") : tr("Your message to FloBrain")}>
            <input className="v2-input w-full" required maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
        </div>
        <Button type="submit" disabled={busy || !text.trim()}>
          {busy ? tr("Running...") : tr("Simulate")}
        </Button>
        {error ? <Notice kind="error">{error}</Notice> : null}
        {result ? (
          <div className="mt-4 grid gap-3" role="status">
            <div className="rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-sm">
              <p className="mb-1 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
                <Badge>{tr("Simulated")}</Badge>
                {chosen === "slack" ? tr("FloBrain replies in the thread:") : tr("FloBrain replies in the conversation:")}
              </p>
              <p className="whitespace-pre-wrap" dir="auto">
                {result.reply || tr("No reply. Outcome: {outcome}", { outcome: result.outcome })}
              </p>
            </div>
            {result.cards.map((card) => (
              <ApprovalPreview key={card.id} orgId={orgId} card={card} onDecided={replaceCard} />
            ))}
            <details className="text-xs text-[color:var(--fb-v2-text-muted)]">
              <summary className="cursor-pointer">{tr("What FloBrain would send ({n} calls)", { n: result.posts.length })}</summary>
              <ul className="mt-2 space-y-1" dir="ltr">
                {result.posts.map((p, i) => (
                  <li key={i}>
                    <span className="font-mono">{p.call}</span> {p.text ? `· ${p.text.slice(0, 120)}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        ) : null}
      </form>
    </Section>
  );
}
