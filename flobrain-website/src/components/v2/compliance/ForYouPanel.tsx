"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { ReviewBoard } from "./ReviewBoard";
import type { MyPolicy, Review } from "./types";

function PolicyCard({ orgId, policy, onDone }: { orgId: string; policy: MyPolicy; onDone: () => void }) {
  const tr = useTr();
  const [open, setOpen] = useState(!policy.acknowledged_at);
  const [read, setRead] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const body = `policy-${policy.id}`;
  async function ack() {
    setError(null);
    try {
      await api.post(`/orgs/${orgId}/compliance/policies/${policy.id}/acknowledge`, { version: policy.version });
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <li className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" className="text-start font-medium" aria-expanded={open} aria-controls={body} onClick={() => setOpen((v) => !v)}>
          {policy.title}
          <span className="ms-2 text-xs font-normal text-[color:var(--fb-v2-text-muted)]">{tr("Version {n}", { n: policy.version })}</span>
        </button>
        {policy.acknowledged_at ? <Badge tone="good">{tr("Acknowledged {when}", { when: when(policy.acknowledged_at) })}</Badge> : <Badge>{tr("To read")}</Badge>}
      </div>
      {open ? (
        <div id={body}>
          <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-[color:var(--fb-v2-raised)] p-3 font-sans text-sm leading-relaxed" dir="auto" tabIndex={0}>
            {policy.body}
          </pre>
          {!policy.acknowledged_at ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />
                {tr("I read this policy and will follow it")}
              </label>
              <Button disabled={!read} onClick={ack}>
                {tr("Acknowledge")}
              </Button>
            </div>
          ) : null}
          {error ? <Notice kind="error">{error}</Notice> : null}
        </div>
      ) : null}
    </li>
  );
}

/** What any member sees: policies to acknowledge, and access review items they were asked to decide. */
export function ForYouPanel({ orgId }: { orgId: string }) {
  const tr = useTr();
  const policies = useOrgData<MyPolicy[]>(orgId, "/compliance/my-policies");
  const reviews = useOrgData<Review[]>(orgId, "/compliance/my-reviews");
  const mine = policies.data ?? [];
  const toReview = reviews.data ?? [];
  return (
    <>
      {toReview.map((r) => (
        <Section key={r.id} title={tr("Your access review items")}>
          <ReviewBoard orgId={orgId} reviewId={r.id} canView={false} canManage={false} />
        </Section>
      ))}
      <Section title={tr("Policies to read")}>
        <ScreenBody state={policies.state === "ready" && !mine.length ? "empty" : policies.state} error={policies.error} emptyLabel={tr("No policies are published yet.")} onRetry={policies.reload}>
          <ul className="space-y-3">
            {mine.map((p) => (
              <PolicyCard key={`${p.id}-${p.version}`} orgId={orgId} policy={p} onDone={policies.reload} />
            ))}
          </ul>
        </ScreenBody>
      </Section>
    </>
  );
}
