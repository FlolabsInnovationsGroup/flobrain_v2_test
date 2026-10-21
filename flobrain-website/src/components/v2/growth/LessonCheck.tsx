"use client";

import { Check, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { localized, type CheckResult, type LessonDetail } from "./growth";

/** A lesson's short check: one choice per question, graded on the server. */
export function LessonCheck({
  orgId,
  lesson,
  onGraded,
}: {
  orgId: string;
  lesson: LessonDetail;
  onGraded: (result: CheckResult) => void;
}) {
  const tr = useTr();
  const locale = useLocale();
  const [answers, setAnswers] = useState<(number | null)[]>(() => lesson.check.map(() => null));
  const [result, setResult] = useState<CheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = answers.every((a) => a !== null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const graded = await api.post<CheckResult>(`/orgs/${orgId}/academy/lessons/${lesson.key}/check`, { answers });
      setResult(graded);
      onGraded(graded);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      {lesson.check.map((q, qi) => {
        const options = locale === "ar" && q.options_ar.length === q.options.length ? q.options_ar : q.options;
        const verdict = result ? result.correct[qi] : null;
        return (
          <fieldset key={qi} className="rounded-lg border border-[color:var(--fb-v2-border)] p-3">
            <legend className="px-1 text-sm font-medium">
              {qi + 1}. {localized(locale, q.question, q.question_ar)}
            </legend>
            <div className="mt-1 flex flex-col gap-1.5">
              {options.map((option, oi) => {
                const right = result?.answers ? result.answers[qi] === oi : false;
                return (
                  <label
                    key={oi}
                    className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-[color:var(--fb-v2-raised)] has-[:checked]:bg-[color:var(--fb-v2-accent-soft)] has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[color:var(--fb-v2-accent)]"
                  >
                    <input
                      type="radio"
                      className="mt-1"
                      name={`${lesson.key}-${qi}`}
                      checked={answers[qi] === oi}
                      onChange={() => {
                        setAnswers((all) => all.map((a, i) => (i === qi ? oi : a)));
                        setResult(null);
                      }}
                    />
                    <span className="flex-1">{option}</span>
                    {right ? <Check size={16} aria-label={tr("Right answer")} className="text-[color:var(--fb-v2-success)]" /> : null}
                  </label>
                );
              })}
            </div>
            {verdict !== null ? (
              <p className="mt-2 flex items-center gap-1 text-xs" style={{ color: verdict ? "var(--fb-v2-success)" : "var(--fb-v2-error)" }}>
                {verdict ? <Check size={14} aria-hidden /> : <X size={14} aria-hidden />}
                {verdict ? tr("Right") : tr("Not quite")}
              </p>
            ) : null}
          </fieldset>
        );
      })}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {result ? (
        <Notice kind={result.passed ? "ok" : "info"}>
          {result.passed
            ? tr("Passed with {score}%. Lesson complete.", { score: result.score })
            : tr("{score}%. You need two thirds right. Read the lesson again and retry.", { score: result.score })}
        </Notice>
      ) : null}
      <div>
        <Button type="submit" disabled={!ready || busy}>
          {result && !result.passed ? tr("Try again") : tr("Check my answers")}
        </Button>
      </div>
    </form>
  );
}
