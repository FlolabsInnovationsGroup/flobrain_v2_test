"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { feedbackBody, nextRating, REASONS, type Rating } from "./crew";

export type FeedbackRow = { message: number; buddy: string; rating: Rating; reason: string };

/**
 * Your own ratings in one buddy thread, as ``{message id: rating}``. Empty when the feature is off
 * (the endpoint answers 501) so chat screens can always call it.
 */
export function useThreadFeedback(orgId: string | null, threadId: number | null) {
  const [ratings, setRatings] = useState<Record<number, Rating>>({});
  const load = useCallback(() => {
    if (!orgId || !threadId) return;
    api
      .get<FeedbackRow[]>(`/orgs/${orgId}/buddies/feedback`, { thread: String(threadId) })
      .then((rows) => setRatings(Object.fromEntries(rows.map((r) => [r.message, r.rating]))))
      .catch(() => setRatings({}));
  }, [orgId, threadId]);
  useEffect(load, [load]);
  return { ratings, reload: load };
}

const iconButton =
  "inline-flex h-8 w-8 items-center justify-center rounded-lg text-[color:var(--fb-v2-text-muted)] hover:bg-[color:var(--fb-v2-border)] hover:text-[color:var(--fb-v2-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fb-v2-accent)] aria-pressed:bg-[color:var(--fb-v2-accent-soft)] aria-pressed:text-[color:var(--fb-v2-accent)]";

/**
 * Thumbs up or down on one buddy reply, with an optional reason when it was not helpful.
 * Mount it under each assistant message that has an ``id``. For a Flo reply, pass ``buddy`` to rate
 * one of the buddies that answered (the first one is rated by default).
 */
export function Feedback({
  orgId,
  messageId,
  initial = null,
  buddy,
  onChange,
}: {
  orgId: string;
  messageId: number;
  initial?: Rating | null;
  buddy?: string;
  onChange?: (rating: Rating | null) => void;
}) {
  const tr = useTr();
  const [rating, setRating] = useState<Rating | null>(initial);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setRating(initial), [initial]);

  async function save(next: Rating | null, withReason = "", withNote = "") {
    setBusy(true);
    setStatus(null);
    try {
      if (next === null) await api.del(`/orgs/${orgId}/buddies/feedback/${messageId}`);
      else await api.post(`/orgs/${orgId}/buddies/feedback`, feedbackBody(messageId, next, withReason, withNote, buddy));
      setRating(next);
      onChange?.(next);
      setStatus({ kind: "ok", text: next === null ? tr("Rating removed") : tr("Thanks for the feedback") });
      return true;
    } catch (err) {
      setStatus({ kind: "error", text: errorText(err) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function click(clicked: Rating) {
    const next = nextRating(rating, clicked);
    if (await save(next)) setAsking(next === "down");
  }

  return (
    <div className="mt-1 text-sm">
      <div className="flex items-center gap-1" role="group" aria-label={tr("Was this helpful?")}>
        <button type="button" className={iconButton} aria-pressed={rating === "up"} aria-label={tr("Helpful")} title={tr("Helpful")} disabled={busy} onClick={() => click("up")}>
          <ThumbsUp className="h-4 w-4" aria-hidden />
        </button>
        <button type="button" className={iconButton} aria-pressed={rating === "down"} aria-label={tr("Not helpful")} title={tr("Not helpful")} disabled={busy} onClick={() => click("down")}>
          <ThumbsDown className="h-4 w-4" aria-hidden />
        </button>
        {status ? (
          <span role={status.kind === "error" ? "alert" : "status"} className="ms-2 text-xs" style={{ color: status.kind === "error" ? "var(--fb-v2-error)" : "var(--fb-v2-text-muted)" }}>
            {status.text}
          </span>
        ) : null}
      </div>
      {asking ? (
        <form
          className="mt-2 max-w-md space-y-2 rounded-lg bg-[color:var(--fb-v2-raised)] p-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await save("down", reason, note)) setAsking(false);
          }}
        >
          <fieldset>
            <legend className="mb-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("What went wrong? (optional)")}</legend>
            <div className="flex flex-wrap gap-1">
              {REASONS.map(([code, label]) => (
                <button
                  key={code}
                  type="button"
                  aria-pressed={reason === code}
                  onClick={() => setReason(reason === code ? "" : code)}
                  className="rounded-full px-2.5 py-1 text-xs ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:bg-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] aria-pressed:bg-[color:var(--fb-v2-accent)] aria-pressed:text-white"
                >
                  {tr(label)}
                </button>
              ))}
            </div>
          </fieldset>
          <input
            className="v2-input"
            maxLength={300}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={tr("Add a note (optional)")}
            aria-label={tr("Note")}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>
              {tr("Send feedback")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setAsking(false)}>
              {tr("Skip")}
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
