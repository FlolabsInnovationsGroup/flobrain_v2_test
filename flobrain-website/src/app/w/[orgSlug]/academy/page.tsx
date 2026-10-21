"use client";

import { Award, CheckCircle2, Circle, Clock } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

import { CoachPanel } from "@/components/v2/growth/CoachPanel";
import { firstOpen, localized, workspaceHref, type Academy, type CheckResult, type LessonDetail } from "@/components/v2/growth/growth";
import { LessonCheck } from "@/components/v2/growth/LessonCheck";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Badge, Notice, PageHeader, Section, when } from "@/components/v2/ui/kit";
import { useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

export default function AcademyPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId, access } = useAccess();
  const tr = useTr();
  const locale = useLocale();
  const { data, state, error, reload, setData } = useOrgData<Academy>(orgId, "/academy");
  const [selected, setSelected] = useState<string | null>(null);
  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [lessonError, setLessonError] = useState<string | null>(null);
  const [badgeNews, setBadgeNews] = useState(false);
  const lessons = data?.lessons ?? [];
  const current = selected ?? firstOpen(lessons)?.key ?? lessons[0]?.key ?? null;

  useEffect(() => {
    if (!orgId || !current) return;
    let cancelled = false;
    api
      .get<LessonDetail>(`/orgs/${orgId}/academy/lessons/${current}`)
      .then((detail) => {
        if (cancelled) return;
        setLesson(detail);
        setLessonError(null);
        if (!detail.progress.read) api.post(`/orgs/${orgId}/academy/lessons/${current}/progress`, { step: "read" }).catch(() => undefined);
      })
      .catch((err) => !cancelled && setLessonError(errorText(err)));
    return () => {
      cancelled = true;
    };
  }, [orgId, current]);

  function open(key: string) {
    setSelected(key);
    document.getElementById("lesson")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function graded(result: CheckResult) {
    if (!data || !lesson) return;
    const lessonsNext = data.lessons.map((l) => (l.key === lesson.key ? { ...l, progress: result.progress } : l));
    setData({ ...data, lessons: lessonsNext, done: lessonsNext.filter((l) => l.progress.completed).length });
    if (result.badge_awarded) {
      setBadgeNews(true);
      reload();
    }
  }

  function tried() {
    if (orgId && lesson) api.post(`/orgs/${orgId}/academy/lessons/${lesson.key}/progress`, { step: "tried" }).catch(() => undefined);
  }

  const pct = data && data.total ? Math.round((100 * data.done) / data.total) : 0;
  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Academy")}
        intro={tr("Short lessons on using FloBrain well. Each one has a step to try in your workspace and a quick check.")}
        action={
          data?.badge ? (
            <span className="inline-flex items-center gap-2 rounded-full bg-[color:var(--fb-v2-accent-soft)] px-3 py-1.5 text-sm font-medium">
              <Award size={16} aria-hidden className="text-[color:var(--fb-v2-accent)]" />
              {tr("Academy graduate since {date}", { date: when(data.badge.awarded_at) })}
            </span>
          ) : null
        }
      />
      {badgeNews ? <Notice kind="ok">{tr("You finished every lesson and earned the Academy badge.")}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data ? (
          <div className="mb-6">
            <div className="flex items-center justify-between text-sm">
              <span>{tr("{done} of {total} lessons done", { done: data.done, total: data.total })}</span>
              <span className="tabular-nums text-[color:var(--fb-v2-text-muted)]">{pct}%</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-[color:var(--fb-v2-track)]" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <div className="h-full rounded-full bg-[color:var(--fb-v2-success)]" style={{ width: `${pct}%` }} />
            </div>
          </div>
        ) : null}
        <div className="grid gap-6 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
          <nav aria-label={tr("Lessons")}>
            <ol className="flex flex-col gap-1">
              {lessons.map((l, i) => {
                const active = l.key === current;
                return (
                  <li key={l.key}>
                    <button
                      type="button"
                      onClick={() => open(l.key)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "flex w-full items-start gap-3 rounded-lg px-3 py-2 text-start text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]",
                        active ? "bg-[color:var(--fb-v2-accent-soft)]" : "hover:bg-[color:var(--fb-v2-surface)]",
                      )}
                    >
                      {l.progress.completed ? (
                        <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-[color:var(--fb-v2-success)]" aria-label={tr("Done")} />
                      ) : (
                        <Circle size={18} className="mt-0.5 shrink-0 text-[color:var(--fb-v2-text-faint)]" aria-hidden />
                      )}
                      <span className="min-w-0">
                        <span className="block font-medium">
                          {i + 1}. {tr(l.title)}
                        </span>
                        <span className="flex items-center gap-1 text-xs text-[color:var(--fb-v2-text-muted)]">
                          <Clock size={12} aria-hidden />
                          {tr("{n} min", { n: l.minutes })}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
          <div className="flex min-w-0 flex-col gap-6">
            <article id="lesson" className="scroll-mt-20 rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
              {lessonError ? <Notice kind="error">{lessonError}</Notice> : null}
              {lesson ? (
                <>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="text-xl font-semibold">{tr(lesson.title)}</h2>
                      <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">{tr(lesson.summary)}</p>
                    </div>
                    {lesson.progress.completed ? <Badge tone="good">{tr("Complete")}</Badge> : null}
                  </div>
                  <div className="v2-prose mt-4 text-sm leading-relaxed [&_h2]:mb-1 [&_h2]:mt-4 [&_h2]:text-base [&_h2]:font-semibold [&_li]:ms-5 [&_ol]:list-decimal [&_p]:my-2 [&_ul]:list-disc">
                    <ReactMarkdown>{localized(locale, lesson.body, lesson.body_ar)}</ReactMarkdown>
                  </div>
                  <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg border border-[color:var(--fb-v2-border)] p-3">
                    <p className="min-w-0 flex-1 text-sm">
                      <span className="font-medium">{tr("Try it")}: </span>
                      {tr("Do it once in your workspace, then come back for the check.")}
                    </p>
                    <Link
                      href={workspaceHref(orgSlug, lesson.try_it.path)}
                      onClick={tried}
                      className="inline-flex items-center rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-accent)] px-3 py-2 text-sm font-medium text-white hover:bg-[color:var(--fb-v2-accent-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fb-v2-accent)]"
                    >
                      {tr(lesson.try_it.label)}
                    </Link>
                  </div>
                  {lesson.feature && access && !access.flags[lesson.feature] ? (
                    <Notice>{tr("This feature is switched off for you. An admin can ask for it to be turned on.")}</Notice>
                  ) : null}
                  <Section title={tr("Quick check")}>
                    {orgId ? <LessonCheck key={lesson.key} orgId={orgId} lesson={lesson} onGraded={graded} /> : null}
                  </Section>
                </>
              ) : !lessonError ? (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Loading")}…</p>
              ) : null}
            </article>
            {orgId && has(access, "ai.use") ? <CoachPanel orgId={orgId} lessonKey={current} onOpenLesson={open} /> : null}
          </div>
        </div>
      </ScreenBody>
    </div>
  );
}
