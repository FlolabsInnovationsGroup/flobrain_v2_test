"use client";

import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useOrgData } from "@/lib/v2/useOrgData";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";

import { orderResults, regressions, score, type CaseResult, type CheckRow, type RunDetail } from "./evals";

function useLabels() {
  const tr = useTr();
  return {
    check: (key: string) =>
      ({
        must_include: tr("Must say"),
        must_not_include: tr("Must not say"),
        must_cite: tr("Cites a source"),
        expected_tool: tr("Expected action"),
        forbidden_tools: tr("Forbidden actions"),
        max_words: tr("Word limit"),
        language: tr("Answer language"),
      })[key] ?? key,
    error: (code: string) =>
      ({
        skipped_budget: tr("Skipped: the run reached its budget."),
        run_budget: tr("Skipped: the run reached its budget."),
        budget_exceeded: tr("Your org's AI budget is used up."),
        not_configured: tr("No AI provider is set up."),
        private_only: tr("Your org only allows self-hosted AI, and none is set up."),
        provider_error: tr("The AI provider did not answer."),
        no_user: tr("The person who started it is no longer here."),
        internal_error: tr("Something went wrong while running."),
      })[code] ?? code,
  };
}

function useReason() {
  const tr = useTr();
  return (row: CheckRow): string => {
    const exp = String(row.expected ?? "");
    const got = String(row.got ?? "");
    switch (row.check) {
      case "must_include":
        return tr("The answer does not say “{p}”.", { p: exp });
      case "must_not_include":
        return tr("The answer says “{p}”, which it must not.", { p: exp });
      case "must_cite":
        return tr("The answer does not cite a source.");
      case "expected_tool":
        return exp === "no action" ? tr("It prepared an action when none was expected.") : tr("It did not prepare {tool}.", { tool: exp });
      case "forbidden_tools":
        return tr("It prepared a forbidden action: {tools}.", { tools: got });
      case "max_words":
        return tr("{got} words; the limit is {max}.", { got, max: exp });
      case "language":
        return tr("The answer is not in the expected language.");
      default:
        return row.reason;
    }
  };
}

function CheckLine({ row }: { row: CheckRow }) {
  const labels = useLabels();
  const reason = useReason();
  const tr = useTr();
  return (
    <li className="flex items-start gap-2 text-sm">
      <span aria-hidden className={row.passed ? "text-[color:var(--fb-v2-success)]" : "text-[color:var(--fb-v2-error)]"}>
        {row.passed ? "✓" : "✕"}
      </span>
      <span>
        <span className="font-medium">{labels.check(row.check)}</span>
        <span className="sr-only">{row.passed ? tr("passed") : tr("failed")}</span>
        {row.check === "must_include" || row.check === "must_not_include" ? <span className="text-[color:var(--fb-v2-text-muted)]">: “{String(row.expected)}”</span> : null}
        {!row.passed ? <span className="block text-[color:var(--fb-v2-text-muted)]">{reason(row)}</span> : null}
      </span>
    </li>
  );
}

function CaseCard({ r, wasPassing }: { r: CaseResult; wasPassing: boolean | undefined }) {
  const tr = useTr();
  const labels = useLabels();
  const e = r.expect ?? {};
  const expectations = [
    ...(e.must_include ?? []).map((p) => tr("Says “{p}”", { p })),
    ...(e.must_not_include ?? []).map((p) => tr("Never says “{p}”", { p })),
    ...(e.must_cite ? [tr("Cites a source")] : []),
    ...(e.expected_tool === "none" ? [tr("Prepares no action")] : e.expected_tool ? [tr("Prepares {tool}", { tool: e.expected_tool })] : []),
    ...((e.forbidden_tools ?? []).length ? [tr("Never prepares {tools}", { tools: (e.forbidden_tools ?? []).join(", ") })] : []),
    ...(e.max_words ? [tr("At most {n} words", { n: e.max_words })] : []),
    ...(e.language === "ar" ? [tr("Answers in Arabic")] : e.language === "en" ? [tr("Answers in English")] : []),
  ];
  const regressed = !r.passed && wasPassing;
  return (
    <details open={!r.passed} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]">
        <span className="min-w-0 flex-1">
          <span className="block font-medium">{r.name || r.input.slice(0, 80)}</span>
          {r.name ? <span className="block truncate text-sm text-[color:var(--fb-v2-text-muted)]">{r.input}</span> : null}
        </span>
        <span className="flex items-center gap-2">
          {regressed ? <Badge tone="bad">{tr("New failure")}</Badge> : null}
          <span className="font-mono text-sm tabular-nums">{score(Math.round(r.score * 1000) / 10)}</span>
          <Badge tone={r.passed ? "good" : "bad"}>{r.passed ? tr("Passed") : tr("Failed")}</Badge>
        </span>
      </summary>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <section aria-label={tr("Expected")}>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">{tr("Expected")}</h4>
          {expectations.length ? (
            <ul className="list-disc space-y-0.5 ps-5 text-sm">
              {expectations.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No fixed checks.")}</p>
          )}
          {e.rubric ? <p className="mt-2 text-sm"><span className="font-medium">{tr("Judge looks for:")}</span> {e.rubric}</p> : null}
          {r.sources.length ? (
            <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
              {tr("Sources: {list}", { list: r.sources.map((s) => s.title || tr("a document you can't open")).join(", ") })}
            </p>
          ) : null}
          {r.missing_sources ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} source(s) were not readable by the person who ran it.", { n: r.missing_sources })}</p> : null}
        </section>
        <section aria-label={tr("Got")}>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-[color:var(--fb-v2-text-muted)]">{tr("Got")}</h4>
          {r.error ? <Notice kind="error">{labels.error(r.error)}</Notice> : null}
          {r.hidden ? (
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Hidden: this answer used a document you can't open.")}</p>
          ) : r.answer ? (
            <p className="whitespace-pre-wrap rounded-lg bg-[color:var(--fb-v2-page)] p-3 text-sm" dir="auto">{r.answer}</p>
          ) : null}
          {r.calls.length ? (
            <ul className="mt-2 space-y-1 text-sm">
              {r.calls.map((c, i) => (
                <li key={`${c.tool}-${i}`} className="rounded-lg border border-[color:var(--fb-v2-border)] px-3 py-1.5">
                  <span className="font-medium">{tr("Would prepare: {tool}", { tool: c.tool })}</span>
                  <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Captured only. Nothing was proposed or run.")}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>
      {r.checks.length ? (
        <ul className="mt-3 space-y-1 border-t border-[color:var(--fb-v2-border)] pt-3">
          {r.checks.map((c, i) => (
            <CheckLine key={`${c.check}-${i}`} row={c} />
          ))}
        </ul>
      ) : null}
      {r.judge ? (
        <p className="mt-2 text-sm">
          <span className="font-medium">{tr("AI judge")}:</span>{" "}
          {r.judge.valid ? (
            <>
              <span className="font-mono tabular-nums">{r.judge.score}/5</span>
              {r.judge.reason ? <span className="text-[color:var(--fb-v2-text-muted)]"> · {r.judge.reason}</span> : null}
            </>
          ) : (
            <span className="text-[color:var(--fb-v2-error)]">{r.judge.error === "skipped_budget" ? labels.error("skipped_budget") : tr("No valid verdict, so this part failed.")}</span>
          )}
        </p>
      ) : null}
    </details>
  );
}

export function RunView({ orgId, runId }: { orgId: string; runId: string }) {
  const tr = useTr();
  const labels = useLabels();
  const { data, state, error, reload } = useOrgData<RunDetail>(orgId, `/evals/runs/${runId}`);
  return (
    <ScreenBody state={state} error={error} onRetry={reload}>
      {data ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="font-mono text-xl font-semibold tabular-nums">{score(data.score)}</span>
            <Badge tone={data.passed ? "good" : "bad"}>{data.passed ? tr("Passed") : data.status === "done" ? tr("Below the pass mark") : tr("Did not finish")}</Badge>
            <span>{tr("{a} of {b} cases passed", { a: data.cases_passed, b: data.cases_total })}</span>
            <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Version {v}", { v: data.version })} · {when(data.created_at)}</span>
            {data.previous ? (
              <span className="text-[color:var(--fb-v2-text-muted)]">
                {tr("Previous version {v}: {s}", { v: data.previous.version, s: score(data.previous.score) })}
              </span>
            ) : null}
          </div>
          {data.error ? <Notice kind="error">{labels.error(data.error)}</Notice> : null}
          {regressions(data).length ? (
            <Notice kind="error">{tr("{n} case(s) passed before and fail now. They are listed first.", { n: regressions(data).length })}</Notice>
          ) : null}
          {orderResults(data).map((r) => (
            <CaseCard key={r.case} r={r} wasPassing={data.previous_results?.[r.case]?.passed} />
          ))}
        </div>
      ) : null}
    </ScreenBody>
  );
}
