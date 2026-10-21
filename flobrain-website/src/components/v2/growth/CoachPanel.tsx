"use client";

import { Send, Sparkles } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

type Turn = { role: "you" | "coach"; text: string; next?: { key: string; title: string } | null };

/** The Academy coach: answers questions about using FloBrain from the lessons and your own workspace use. */
export function CoachPanel({
  orgId,
  lessonKey,
  onOpenLesson,
}: {
  orgId: string;
  lessonKey: string | null;
  onOpenLesson: (key: string) => void;
}) {
  const tr = useTr();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setTurns((all) => [...all, { role: "you", text }]);
    setQuestion("");
    try {
      const out = await api.post<{ answer: string; next_lesson: { key: string; title: string } | null }>(`/orgs/${orgId}/academy/coach`, {
        question: text,
        ...(lessonKey ? { lesson: lessonKey } : {}),
      });
      setTurns((all) => [...all, { role: "coach", text: out.answer, next: out.next_lesson }]);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
      requestAnimationFrame(() => end.current?.scrollIntoView({ block: "nearest" }));
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4" aria-labelledby="coach-title">
      <div>
        <h2 id="coach-title" className="flex items-center gap-2 font-semibold">
          <Sparkles size={16} aria-hidden className="text-[color:var(--fb-v2-accent)]" />
          {tr("Ask the coach")}
        </h2>
        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
          {tr("Answers from the lessons and what is switched on for you. It never sees other people's work.")}
        </p>
      </div>
      {turns.length ? (
        <div className="max-h-80 overflow-y-auto" aria-live="polite">
        <ol className="flex flex-col gap-2">
          {turns.map((t, i) => (
            <li
              key={i}
              className={
                t.role === "you"
                  ? "self-end rounded-lg bg-[color:var(--fb-v2-accent-soft)] px-3 py-2 text-sm"
                  : "self-start rounded-lg bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm"
              }
            >
              <span className="sr-only">{t.role === "you" ? tr("You said") : tr("The coach said")}: </span>
              <p className="whitespace-pre-wrap">{t.text}</p>
              {t.next ? (
                <button type="button" className="mt-2 text-xs font-medium text-[color:var(--fb-v2-accent)] hover:underline" onClick={() => onOpenLesson(t.next!.key)}>
                  {tr("Open the next lesson: {title}", { title: tr(t.next.title) })}
                </button>
              ) : null}
            </li>
          ))}
        </ol>
          <div ref={end} />
        </div>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <form onSubmit={ask} className="flex items-end gap-2">
        <label className="min-w-0 flex-1">
          <span className="sr-only">{tr("Your question")}</span>
          <textarea
            className="v2-input w-full"
            rows={2}
            maxLength={1000}
            value={question}
            placeholder={tr("For example: how do I make a buddy for my team?")}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                (e.currentTarget.form as HTMLFormElement | null)?.requestSubmit();
              }
            }}
          />
        </label>
        <Button type="submit" disabled={busy || !question.trim()} aria-label={tr("Ask")}>
          <Send size={16} aria-hidden className="rtl:-scale-x-100" />
        </Button>
      </form>
    </section>
  );
}
