"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";

type Citation = { n: number; source_type: string; source_id: string; room?: string; title: string; excerpt: string };
type Answer = { answer: string; citations: Citation[] };

const SUGGESTIONS = ["What is the launch plan?", "Who owns the store screenshots?", "What is blocking the Android release?"];

export default function AskPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId } = useAccess();
  const tr = useTr();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function ask(text: string) {
    if (!orgId || !text.trim()) return;
    setBusy(true);
    setError("");
    setQuestion(text);
    try {
      setAnswer(await api.post<Answer>(`/orgs/${orgId}/knowledge/ask`, { question: text }));
    } catch (err) {
      setError(errorText(err));
      setAnswer(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={tr("Ask the org")}
        intro={tr("Ask a question and get an answer from the rooms and documents you can open. Every answer lists its sources.")}
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          ask(question);
        }}
        className="flex gap-2"
      >
        <input
          className="v2-input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={tr("What do you want to know?")}
          aria-label={tr("Question")}
        />
        <Button type="submit" disabled={busy || !question.trim()}>
          {busy ? tr("Asking…") : tr("Ask")}
        </Button>
      </form>
      {!answer && !busy ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((text) => (
            <Button key={text} type="button" variant="outline" onClick={() => ask(text)}>
              {tr(text)}
            </Button>
          ))}
        </div>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {answer ? (
        <article className="mt-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
          <p className="whitespace-pre-wrap">{answer.answer}</p>
          {answer.citations.length ? (
            <>
              <h2 className="mb-2 mt-5 text-sm font-semibold">{tr("Sources")}</h2>
              <ol className="space-y-2 text-sm">
                {answer.citations.map((c) => (
                  <li key={`${c.n}-${c.source_id}`} className="flex gap-2">
                    <span className="text-[color:var(--fb-v2-text-muted)]">[{c.n}]</span>
                    <span>
                      {c.room ? (
                        <Link className="font-medium hover:underline" href={`/w/${orgSlug}/rooms/${c.room}`}>
                          {c.title}
                        </Link>
                      ) : (
                        <span className="font-medium">{c.title}</span>
                      )}
                      <span className="block text-[color:var(--fb-v2-text-muted)]">{c.excerpt}</span>
                    </span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <Notice>{tr("No sources you can open matched this question.")}</Notice>
          )}
        </article>
      ) : null}
    </div>
  );
}
