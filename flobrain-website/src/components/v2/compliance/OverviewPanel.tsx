"use client";

import Link from "next/link";

import { Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { Pct, ReadinessBar, StatusBadge } from "./bits";
import { checkTitle } from "./checkTitles";
import type { CheckResult, Overview } from "./types";

function Evidence({ check, orgSlug }: { check: CheckResult; orgSlug: string }) {
  if (!check.evidence.length) return null;
  return (
    <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[color:var(--fb-v2-text-muted)]">
      {check.evidence.map((e, i) => (
        <li key={i}>
          <span>{e.label}: </span>
          {e.link ? (
            <Link className="v2-mono underline underline-offset-2" href={`/w/${orgSlug}/${e.link}`}>
              {e.value}
            </Link>
          ) : (
            <span className="v2-mono" dir="auto">
              {e.value}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function CheckList({ checks, orgSlug }: { checks: CheckResult[]; orgSlug: string }) {
  const tr = useTr();
  const order = { fail: 0, manual: 1, pass: 2, not_applicable: 3 } as const;
  const sorted = [...checks].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <Rows>
      {sorted.map((c) => (
        <Row key={c.key} className="items-start">
          <div className="min-w-0 flex-1 basis-72">
            <p className="font-medium">{checkTitle(tr, c.key, c.title)}</p>
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]" dir="auto">
              {c.summary}
            </p>
            <Evidence check={c} orgSlug={orgSlug} />
          </div>
          <StatusBadge status={c.status} />
        </Row>
      ))}
    </Rows>
  );
}

export function OverviewPanel({ data, orgSlug, onTab }: { data: Overview; orgSlug: string; onTab: (tab: "controls" | "reviews" | "evidence" | "policies" | "trust") => void }) {
  const tr = useTr();
  const gaps = data.checks.filter((c) => c.status === "fail").length;
  return (
    <>
      <Notice>{tr("Readiness, not certification: these numbers come from automated checks on your FloBrain data and from your own attestations, not from an auditor.")}</Notice>
      <div className="mb-8 grid gap-4 md:grid-cols-2">
        {data.frameworks.map((fw) => (
          <section key={fw.framework} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" aria-label={fw.name}>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <h2 className="font-semibold">{fw.name}</h2>
              <span className="text-2xl font-semibold">
                <Pct value={fw.readiness} />
              </span>
            </div>
            <ReadinessBar value={fw.readiness} label={tr("{name} readiness", { name: fw.short })} />
            <p className="v2-mono mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
              {tr("{pass} passing · {fail} gaps · {manual} need evidence · {na} not applicable", {
                pass: fw.counts.pass,
                fail: fw.counts.fail,
                manual: fw.counts.manual,
                na: fw.counts.not_applicable,
              })}
            </p>
            <ul className="mt-4 space-y-2">
              {fw.groups.map((g) => (
                <li key={g.group} className="grid grid-cols-[minmax(0,1fr)_5rem_2.5rem] items-center gap-3 text-sm">
                  <span className="truncate" title={g.name}>
                    <span className="v2-mono me-2 text-xs text-[color:var(--fb-v2-text-faint)]">{g.group}</span>
                    {g.name}
                  </span>
                  <ReadinessBar size="sm" value={g.readiness} label={g.name} />
                  <span className="text-end text-xs">
                    <Pct value={g.readiness} />
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <button type="button" onClick={() => onTab("reviews")} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start hover:bg-[color:var(--fb-v2-raised)]">
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Access review")}</p>
          <p className="font-medium">
            {data.open_review
              ? tr("{done} of {total} decided", { done: data.open_review.progress.decided, total: data.open_review.progress.total })
              : tr("None in progress")}
          </p>
        </button>
        <button type="button" onClick={() => onTab("evidence")} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start hover:bg-[color:var(--fb-v2-raised)]">
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Evidence package")}</p>
          <p className="font-medium">{data.last_evidence ? when(data.last_evidence.created_at) : tr("None yet")}</p>
        </button>
        <button type="button" onClick={() => onTab("policies")} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start hover:bg-[color:var(--fb-v2-raised)]">
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Policies")}</p>
          <p className="v2-mono font-medium">{data.policies}</p>
        </button>
        <button type="button" onClick={() => onTab("trust")} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start hover:bg-[color:var(--fb-v2-raised)]">
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Trust page")}</p>
          <p className="font-medium">{data.trust_published ? tr("Published") : tr("Not published")}</p>
        </button>
      </div>

      <Section title={tr("Automated checks")} aside={<span className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("{n} gaps", { n: gaps })}</span>}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("These read your real settings and records in FloBrain. They cover how you govern access and AI here, which your auditor will ask about. The rest of your controls need evidence from outside FloBrain.")}
        </p>
        <CheckList checks={data.checks} orgSlug={orgSlug} />
      </Section>
    </>
  );
}
