"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { ReadinessBar, inputClass } from "./bits";
import { ReviewBoard } from "./ReviewBoard";
import type { Review } from "./types";

function StatusOf({ review }: { review: Review }) {
  const tr = useTr();
  if (review.status === "open") return <Badge tone="accent">{tr("In progress")}</Badge>;
  if (review.status === "completed") return <Badge tone="good">{tr("Completed")}</Badge>;
  return <Badge>{tr("Cancelled")}</Badge>;
}

function StartForm({ orgId, onStarted }: { orgId: string; onStarted: (r: Review) => void }) {
  const tr = useTr();
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"team_leads" | "admins">("team_leads");
  const [days, setDays] = useState("14");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function start() {
    setBusy(true);
    setError(null);
    try {
      onStarted(await api.post<Review>(`/orgs/${orgId}/compliance/reviews`, { name, reviewer_mode: mode, due_days: Number(days) }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
      onSubmit={(e) => {
        e.preventDefault();
        start();
      }}
    >
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("A review lists every member's role, extra permissions, personal connections and shared buddies. Each item is kept, revoked or changed.")}
      </p>
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label={tr("Name (optional)")} hint={tr("Leave empty to name it after this quarter.")}>
          <input className={inputClass} dir="auto" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={tr("Due in")}>
          <select className={inputClass} value={days} onChange={(e) => setDays(e.target.value)}>
            {["7", "14", "30"].map((d) => (
              <option key={d} value={d}>
                {tr("{n} days", { n: d })}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <fieldset className="mb-4">
        <legend className="mb-1 text-sm font-medium">{tr("Who reviews")}</legend>
        <label className="mb-1 flex items-start gap-2 text-sm">
          <input type="radio" name="review-mode" className="mt-1" checked={mode === "team_leads"} onChange={() => setMode("team_leads")} />
          <span>{tr("Team leads review their team; admins review admins and people without a team")}</span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input type="radio" name="review-mode" className="mt-1" checked={mode === "admins"} onChange={() => setMode("admins")} />
          <span>{tr("Admins review everyone")}</span>
        </label>
      </fieldset>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <Button type="submit" disabled={busy}>
        {tr("Start the review")}
      </Button>
    </form>
  );
}

export function ReviewsPanel({ orgId, canManage, selected, onSelect }: { orgId: string; canManage: boolean; selected: string | null; onSelect: (id: string | null) => void }) {
  const tr = useTr();
  const list = useOrgData<Review[]>(orgId, "/compliance/reviews");
  const [starting, setStarting] = useState(false);
  const reviews = list.data ?? [];
  const hasOpen = reviews.some((r) => r.status === "open");

  if (selected) {
    return <ReviewBoard orgId={orgId} reviewId={selected} canView canManage={canManage} onClose={() => onSelect(null)} onChanged={list.reload} />;
  }

  return (
    <>
      {canManage && !hasOpen ? (
        starting ? (
          <StartForm
            orgId={orgId}
            onStarted={(r) => {
              setStarting(false);
              list.reload();
              onSelect(r.id);
            }}
          />
        ) : (
          <div className="mb-4">
            <Button onClick={() => setStarting(true)}>{tr("Start an access review")}</Button>
          </div>
        )
      ) : null}
      <Section title={tr("Access reviews")}>
        <ScreenBody state={list.state === "ready" && !reviews.length ? "empty" : list.state} error={list.error} emptyLabel={tr("No access reviews yet. Run one every quarter.")} onRetry={list.reload}>
          <Rows>
            {reviews.map((r) => (
              <Row key={r.id}>
                <div className="min-w-0 flex-1 basis-64">
                  <button type="button" className="font-medium underline-offset-2 hover:underline" onClick={() => onSelect(r.id)} dir="auto">
                    {r.name}
                  </button>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {r.status === "completed" && r.completed_at ? tr("Completed {when}", { when: when(r.completed_at) }) : tr("Started {when}", { when: when(r.created_at) })}
                    {r.created_by ? ` · ${tr("by {name}", { name: r.created_by })}` : ""}
                  </p>
                  <div className="mt-2 max-w-sm">
                    <ReadinessBar size="sm" value={r.progress.total ? (100 * r.progress.decided) / r.progress.total : 0} label={tr("Decisions made")} />
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="v2-mono text-xs text-[color:var(--fb-v2-text-muted)]">
                    {r.progress.decided}/{r.progress.total}
                  </span>
                  <StatusOf review={r} />
                </div>
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>
    </>
  );
}
