"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { apiClient } from "@/lib/axios";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { ReadinessBar, inputClass } from "./bits";
import { canChange, nextPending, reviewKey } from "./logic";
import type { Decision, ReviewDetail, ReviewItem, ReviewReport } from "./types";

function DecisionBadge({ item }: { item: ReviewItem }) {
  const tr = useTr();
  if (item.apply_error) return <Badge tone="bad">{tr("Could not apply")}</Badge>;
  if (item.decision === "pending") return <Badge>{tr("Waiting for a decision")}</Badge>;
  if (item.decision === "keep") return <Badge tone="good">{tr("Kept")}</Badge>;
  if (!item.applied_at) return <Badge tone="waiting">{tr("Waiting for an admin to apply")}</Badge>;
  return <Badge tone="good">{item.decision === "revoke" ? tr("Revoked") : tr("Changed")}</Badge>;
}

function KindLabel({ kind }: { kind: ReviewItem["kind"] }) {
  const tr = useTr();
  if (kind === "membership") return <>{tr("Role")}</>;
  if (kind === "grant") return <>{tr("Extra permission")}</>;
  if (kind === "integration") return <>{tr("Personal connection")}</>;
  return <>{tr("Shared buddy")}</>;
}

function Details({ item }: { item: ReviewItem }) {
  const tr = useTr();
  const d = item.details as Record<string, unknown>;
  const parts: string[] = [];
  if (item.kind === "membership") {
    const teams = (d.teams as { name: string; lead: boolean }[] | undefined) ?? [];
    if (teams.length) parts.push(teams.map((t) => (t.lead ? `${t.name} (${tr("lead")})` : t.name)).join(", "));
    parts.push(d.last_active ? tr("Last seen {when}", { when: when(String(d.last_active)) }) : tr("Never signed in"));
  }
  if (item.kind === "grant") {
    parts.push(d.expires_at ? tr("Ends {when}", { when: when(String(d.expires_at)) }) : tr("No end date"));
    if (d.member_status && d.member_status !== "active") parts.push(tr("Person is {status}", { status: String(d.member_status) }));
  }
  if (item.kind === "integration") {
    if (d.account) parts.push(String(d.account));
    parts.push(d.last_used_at ? tr("Last used {when}", { when: when(String(d.last_used_at)) }) : tr("Never used"));
  }
  if (item.kind === "buddy") {
    parts.push(d.visibility === "org" ? tr("Shared with everyone") : tr("Shared with {team}", { team: String(d.team ?? "") }));
    const tools = (d.tools as string[] | undefined) ?? [];
    if (tools.length) parts.push(tr("{n} tools", { n: tools.length }));
  }
  return (
    <p className="text-xs text-[color:var(--fb-v2-text-muted)]" dir="auto">
      {parts.join(" · ")}
    </p>
  );
}

function ChangeEditor({ item, grantDays, onSubmit, onCancel }: { item: ReviewItem; grantDays: number[]; onSubmit: (change: Record<string, unknown>) => void; onCancel: () => void }) {
  const tr = useTr();
  const role = String(item.details.org_role ?? "member");
  const [value, setValue] = useState(item.kind === "grant" ? String(grantDays[1] ?? 30) : role === "admin" ? "member" : "admin");
  const ref = useRef<HTMLSelectElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <form
      className="mt-2 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(item.kind === "grant" ? { expires_in_days: Number(value) } : { org_role: value });
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
        e.stopPropagation();
      }}
    >
      <label className="text-sm">
        <span className="sr-only">{item.kind === "grant" ? tr("End the permission in") : tr("New role")}</span>
        <select ref={ref} className={`${inputClass} w-auto`} value={value} onChange={(e) => setValue(e.target.value)}>
          {item.kind === "grant"
            ? grantDays.map((d) => (
                <option key={d} value={d}>
                  {tr("Ends in {n} days", { n: d })}
                </option>
              ))
            : (["admin", "member"] as const)
                .filter((r) => r !== role)
                .map((r) => (
                  <option key={r} value={r}>
                    {r === "admin" ? tr("Make admin") : tr("Make member")}
                  </option>
                ))}
        </select>
      </label>
      <Button type="submit">{tr("Save change")}</Button>
      <Button type="button" variant="ghost" onClick={onCancel}>
        {tr("Cancel")}
      </Button>
    </form>
  );
}

function Report({ orgId, reviewId }: { orgId: string; reviewId: string }) {
  const tr = useTr();
  const { data } = useOrgData<ReviewReport>(orgId, `/compliance/reviews/${reviewId}/report`);
  const [error, setError] = useState<string | null>(null);
  async function download() {
    setError(null);
    try {
      const res = await apiClient.get<Blob>(`/api/v2/orgs/${orgId}/compliance/reviews/${reviewId}/report`, { params: { export: "csv" }, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `access-review-${data?.review.period || reviewId}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorText(err));
    }
  }
  if (!data) return null;
  const kinds = Object.entries(data.by_kind);
  return (
    <Section title={tr("Completion report")} aside={<Button variant="outline" onClick={download}>{tr("Download CSV")}</Button>}>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
        <table className="w-full min-w-[28rem] text-sm">
          <thead className="text-[color:var(--fb-v2-text-muted)]">
            <tr>
              <th className="px-4 py-2 text-start font-medium">{tr("Access")}</th>
              <th className="px-4 py-2 text-end font-medium">{tr("Kept")}</th>
              <th className="px-4 py-2 text-end font-medium">{tr("Revoked")}</th>
              <th className="px-4 py-2 text-end font-medium">{tr("Changed")}</th>
              <th className="px-4 py-2 text-end font-medium">{tr("review|Open")}</th>
            </tr>
          </thead>
          <tbody className="v2-mono">
            {kinds.map(([kind, c]) => (
              <tr key={kind} className="border-t border-[color:var(--fb-v2-border)]">
                <td className="px-4 py-2 font-sans">
                  <KindLabel kind={kind as ReviewItem["kind"]} />
                </td>
                <td className="px-4 py-2 text-end">{c.keep}</td>
                <td className="px-4 py-2 text-end">{c.revoke}</td>
                <td className="px-4 py-2 text-end">{c.change}</td>
                <td className="px-4 py-2 text-end">{c.pending}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.changes.length ? (
        <ul className="mt-3 space-y-1 text-sm">
          {data.changes.map((c, i) => (
            <li key={i} dir="auto">
              <span className="font-medium">{c.subject}</span>: {c.label} · {c.decision === "revoke" ? tr("Revoked") : tr("Changed")}
              {c.decided_by ? ` · ${tr("by {name}", { name: c.decided_by })}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {data.reviewers.length ? <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Reviewers: {names}", { names: data.reviewers.join(", ") })}</p> : null}
    </Section>
  );
}

export function ReviewBoard({ orgId, reviewId, canView, canManage, onClose, onChanged }: { orgId: string; reviewId: string; canView: boolean; canManage: boolean; onClose?: () => void; onChanged?: () => void }) {
  const tr = useTr();
  const { data, state, error, reload, setData } = useOrgData<ReviewDetail>(orgId, `/compliance/reviews/${reviewId}${canView ? "" : "?mine=1"}`);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null);
  const [changing, setChanging] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [help, setHelp] = useState(false);
  const rows = useRef<(HTMLLIElement | null)[]>([]);
  const items = useMemo(() => (data?.items ?? []).filter((i) => !onlyOpen || i.decision === "pending"), [data, onlyOpen]);
  const open = data?.status === "open";
  const current = items[Math.min(index, Math.max(0, items.length - 1))];

  function focusRow(i: number) {
    setIndex(i);
    requestAnimationFrame(() => rows.current[i]?.focus());
  }

  async function decide(item: ReviewItem, decision: Exclude<Decision, "pending">, change_to?: Record<string, unknown>) {
    setMessage(null);
    try {
      const next = await api.post<ReviewItem>(`/orgs/${orgId}/compliance/reviews/${reviewId}/items/${item.id}/decision`, { decision, change_to });
      setData((prev) => (prev ? { ...prev, items: prev.items.map((i) => (i.id === next.id ? next : i)) } : prev));
      setConfirmRevoke(null);
      setChanging(null);
      const at = items.findIndex((i) => i.id === item.id);
      const updated = items.map((i) => (i.id === next.id ? next : i));
      focusRow(nextPending(updated, at));
      onChanged?.();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setConfirmRevoke(null);
      setChanging(null);
      setHelp(false);
      return;
    }
    const action = reviewKey(e.nativeEvent, index, items.length);
    if (!action) return;
    e.preventDefault();
    if (action.type === "move") return focusRow(action.index);
    if (action.type === "help") return setHelp((v) => !v);
    if (!current || !current.can_decide || !open) return;
    if (action.decision === "keep") return void decide(current, "keep");
    if (action.decision === "revoke") {
      if (confirmRevoke === current.id) return void decide(current, "revoke");
      return setConfirmRevoke(current.id);
    }
    if (canChange(current)) setChanging(current.id);
  }

  async function act(action: "remind" | "apply" | "complete" | "cancel") {
    setMessage(null);
    try {
      const result = await api.post<{ sent?: number; applied?: number }>(`/orgs/${orgId}/compliance/reviews/${reviewId}/${action}`);
      const text =
        action === "remind"
          ? tr("Reminder sent to {n} people.", { n: result.sent ?? 0 })
          : action === "apply"
            ? tr("{n} changes applied.", { n: result.applied ?? 0 })
            : action === "complete"
              ? tr("Review completed.")
              : tr("Review cancelled.");
      setMessage({ kind: "ok", text });
      reload();
      onChanged?.();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <ScreenBody state={state} error={error} onRetry={reload}>
      {data ? (
        <div>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              {onClose ? (
                <button type="button" onClick={onClose} className="mb-1 text-sm text-[color:var(--fb-v2-accent)] underline-offset-2 hover:underline">
                  {tr("All reviews")}
                </button>
              ) : null}
              <h2 className="text-lg font-semibold" dir="auto">
                {data.name}
              </h2>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {data.status === "open"
                  ? data.due_at
                    ? tr("Due {when}", { when: when(data.due_at) })
                    : tr("review|Open")
                  : data.status === "completed"
                    ? tr("Completed {when}", { when: when(data.completed_at) })
                    : tr("Cancelled")}
                {" · "}
                {data.reviewer_mode === "team_leads" ? tr("Team leads review their teams") : tr("Admins review everyone")}
              </p>
            </div>
            {canManage && open ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => act("remind")}>
                  {tr("Send reminder")}
                </Button>
                {data.progress.waiting_apply ? (
                  <Button variant="waiting" onClick={() => act("apply")}>
                    {tr("Apply {n} waiting changes", { n: data.progress.waiting_apply })}
                  </Button>
                ) : null}
                <Button onClick={() => act("complete")} disabled={data.progress.pending > 0 || data.progress.waiting_apply > 0}>
                  {tr("Complete review")}
                </Button>
                <Button variant="danger" onClick={() => act("cancel")}>
                  {tr("Cancel review")}
                </Button>
              </div>
            ) : null}
          </div>
          <ReadinessBar value={data.progress.total ? (100 * data.progress.decided) / data.progress.total : 0} label={tr("Decisions made")} />
          <p className="v2-mono mb-3 mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("{done} of {total} decided", { done: data.progress.decided, total: data.progress.total })}
          </p>
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

          {open ? (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
                {tr("Only items waiting for a decision")}
              </label>
              <button type="button" className="text-[color:var(--fb-v2-text-muted)] underline-offset-2 hover:underline" aria-expanded={help} onClick={() => setHelp((v) => !v)}>
                {tr("Keyboard shortcuts")}
              </button>
            </div>
          ) : null}
          {help ? (
            <div className="mb-3 rounded-lg bg-[color:var(--fb-v2-raised)] p-3 text-sm" role="note">
              <ul className="grid gap-1 sm:grid-cols-2">
                <li>
                  <kbd className="v2-mono">j</kbd> / <kbd className="v2-mono">↓</kbd> {tr("Next item")}
                </li>
                <li>
                  <kbd className="v2-mono">k</kbd> / <kbd className="v2-mono">↑</kbd> {tr("Previous item")}
                </li>
                <li>
                  <kbd className="v2-mono">1</kbd> {tr("Keep")}
                </li>
                <li>
                  <kbd className="v2-mono">2</kbd> {tr("Revoke (press again to confirm)")}
                </li>
                <li>
                  <kbd className="v2-mono">3</kbd> {tr("Change")}
                </li>
                <li>
                  <kbd className="v2-mono">Esc</kbd> {tr("Cancel")}
                </li>
              </ul>
            </div>
          ) : null}

          {items.length ? (
            <ul onKeyDown={onKeyDown} aria-label={tr("Access to review")} className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
              {items.map((item, i) => (
                <li
                  key={item.id}
                  ref={(el) => {
                    rows.current[i] = el;
                  }}
                  tabIndex={i === index ? 0 : -1}
                  onFocus={() => setIndex(i)}
                  aria-current={i === index ? "true" : undefined}
                  className={`px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fb-v2-accent)] ${i === index ? "bg-[color:var(--fb-v2-raised)]" : ""}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 basis-64">
                      <p className="font-medium" dir="auto">
                        {item.subject.name}
                        <span className="ms-2 text-xs font-normal text-[color:var(--fb-v2-text-muted)]">
                          <KindLabel kind={item.kind} />
                        </span>
                      </p>
                      <p className="text-sm" dir="auto">
                        {item.label}
                      </p>
                      <Details item={item} />
                      <p className="text-xs text-[color:var(--fb-v2-text-faint)]">
                        {item.reviewer ? tr("Reviewer: {name}", { name: item.reviewer.name }) : tr("Reviewer: admins")}
                        {item.decided_by ? ` · ${tr("Decided by {name}", { name: item.decided_by })}` : ""}
                      </p>
                      {item.apply_error ? <p className="text-xs text-[color:var(--fb-v2-error)]">{item.apply_error}</p> : null}
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <DecisionBadge item={item} />
                      {item.can_decide && open ? (
                        <div className="flex flex-wrap justify-end gap-1">
                          <Button variant="outline" onClick={() => decide(item, "keep")} aria-keyshortcuts="1">
                            {tr("Keep")}
                          </Button>
                          {confirmRevoke === item.id ? (
                            <Button variant="danger" onClick={() => decide(item, "revoke")} aria-keyshortcuts="2">
                              {tr("Confirm revoke")}
                            </Button>
                          ) : (
                            <Button variant="danger" onClick={() => setConfirmRevoke(item.id)} aria-keyshortcuts="2">
                              {tr("Revoke")}
                            </Button>
                          )}
                          {canChange(item) ? (
                            <Button variant="ghost" onClick={() => setChanging(item.id)} aria-keyshortcuts="3">
                              {tr("Change")}
                            </Button>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {confirmRevoke === item.id ? (
                    <p className="mt-2 text-sm text-[color:var(--fb-v2-error)]" role="alert">
                      {canManage
                        ? tr("This removes the access now and records it in the audit log.")
                        : tr("An admin applies this after you decide.")}
                    </p>
                  ) : null}
                  {changing === item.id ? (
                    <ChangeEditor item={item} grantDays={data.grant_days} onSubmit={(change) => decide(item, "change", change)} onCancel={() => setChanging(null)} />
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="p-6 text-[color:var(--fb-v2-text-muted)]">{onlyOpen ? tr("Every item has a decision.") : tr("Nothing to review here.")}</p>
          )}
          {canView && data.status !== "open" ? <Report orgId={orgId} reviewId={reviewId} /> : null}
        </div>
      ) : null}
    </ScreenBody>
  );
}
