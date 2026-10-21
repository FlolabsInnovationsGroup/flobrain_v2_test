"use client";

import { Star } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { starFill } from "./growth";

export type RatingSummary = { average: number | null; count: number };
export type MyRating = { stars: number; review: string; version: number } | null;
type Review = { id: string; user: string; name: string; stars: number; review: string; version: number; updated_at: string };
type Reviews = { average: number | null; count: number; can_rate: boolean; results: Review[] };
type Version = { id: string; version: number; status: string; changelog: string; verified: boolean; created_at: string; decided_at: string | null };

/** Five stars, read-only. */
export function Stars({ value, size = 14 }: { value: number | null | undefined; size?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-hidden>
      {starFill(value).map((on, i) => (
        <Star
          key={i}
          size={size}
          strokeWidth={1.75}
          className={on ? "fill-[color:var(--fb-v2-accent)] text-[color:var(--fb-v2-accent)]" : "text-[color:var(--fb-v2-text-faint)]"}
        />
      ))}
    </span>
  );
}

/** "Verified by FloBrain" mark, set by FloBrain staff only. */
export function VerifiedMark() {
  const tr = useTr();
  return <Badge tone="accent">{tr("Verified by FloBrain")}</Badge>;
}

/**
 * Rating summary, reviews, a rating form (people who installed it, not its author) and the version
 * history of one marketplace listing. Reviews and history load when opened.
 */
export function ListingRating({
  orgId,
  listingId,
  rating,
  mine,
  installed,
  isAuthor,
  onChanged,
}: {
  orgId: string;
  listingId: string;
  rating?: RatingSummary;
  mine?: MyRating;
  installed: boolean;
  isAuthor: boolean;
  onChanged: () => void;
}) {
  const tr = useTr();
  const [reviews, setReviews] = useState<Reviews | null>(null);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [stars, setStars] = useState<number>(mine?.stars ?? 0);
  const [text, setText] = useState(mine?.review ?? "");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/orgs/${orgId}/marketplace/${listingId}`;

  function loadReviews() {
    api
      .get<Reviews>(`${base}/ratings`)
      .then(setReviews)
      .catch((err) => setMessage({ kind: "error", text: errorText(err) }));
  }

  function loadVersions() {
    api
      .get<{ results: Version[] }>(`${base}/versions`)
      .then((v) => setVersions(v.results))
      .catch((err) => setMessage({ kind: "error", text: errorText(err) }));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (stars < 1) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.post(`${base}/ratings`, { stars, review: text.trim() });
      setMessage({ kind: "ok", text: tr("Thanks. Your rating is saved.") });
      if (reviews) loadReviews();
      onChanged();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setMessage(null);
    try {
      await api.del(`${base}/ratings`);
      setStars(0);
      setText("");
      setMessage({ kind: "ok", text: tr("Your rating is removed.") });
      if (reviews) loadReviews();
      onChanged();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  const count = rating?.count ?? 0;
  const canRate = installed && !isAuthor;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <Stars value={rating?.average} />
        <span className="tabular-nums text-[color:var(--fb-v2-text-muted)]">
          {count
            ? tr("{avg} out of 5, {n} ratings", { avg: (rating?.average ?? 0).toFixed(1), n: count })
            : tr("No ratings yet")}
        </span>
      </p>
      {count ? (
        <details onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && !reviews && loadReviews()}>
          <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Reviews")}</summary>
          {reviews ? (
            <ul className="mt-2 flex flex-col gap-2">
              {reviews.results.map((r) => (
                <li key={r.id} className="rounded-lg border border-[color:var(--fb-v2-border)] p-2">
                  <p className="flex flex-wrap items-center gap-2">
                    <Stars value={r.stars} size={12} />
                    <span className="font-medium">{r.name}</span>
                    <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {tr("Version {n}.", { n: r.version })} {when(r.updated_at)}
                    </span>
                  </p>
                  {r.review ? <p className="mt-1 whitespace-pre-wrap">{r.review}</p> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[color:var(--fb-v2-text-muted)]">{tr("Loading")}…</p>
          )}
        </details>
      ) : null}
      <details onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && !versions && loadVersions()}>
        <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Version history")}</summary>
        {versions ? (
          <ol className="mt-2 flex flex-col gap-1">
            {versions.map((v) => (
              <li key={v.id} className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium tabular-nums">{tr("Version {n}.", { n: v.version })}</span>
                <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{when(v.decided_at ?? v.created_at)}</span>
                {v.verified ? <VerifiedMark /> : null}
                <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  {tr({ approved: "Available", superseded: "Replaced by a newer version", pending: "Waiting for approval", rejected: "Rejected", withdrawn: "Withdrawn" }[v.status] ?? v.status)}
                </span>
                {v.changelog ? <span className="basis-full">{v.changelog}</span> : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-[color:var(--fb-v2-text-muted)]">{tr("Loading")}…</p>
        )}
      </details>
      {canRate ? (
        <details>
          <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{mine ? tr("Change your rating") : tr("Rate it")}</summary>
          <form className="mt-2 flex flex-col gap-2" onSubmit={save}>
            <fieldset className="flex items-center gap-1">
              <legend className="sr-only">{tr("Stars")}</legend>
              {[1, 2, 3, 4, 5].map((n) => (
                <label key={n} className="cursor-pointer rounded p-0.5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[color:var(--fb-v2-accent)]">
                  <input type="radio" name={`stars-${listingId}`} value={n} checked={stars === n} onChange={() => setStars(n)} className="sr-only" />
                  <Star
                    size={20}
                    strokeWidth={1.75}
                    aria-hidden
                    className={n <= stars ? "fill-[color:var(--fb-v2-accent)] text-[color:var(--fb-v2-accent)]" : "text-[color:var(--fb-v2-text-faint)]"}
                  />
                  <span className="sr-only">{tr("{n} out of 5", { n })}</span>
                </label>
              ))}
            </fieldset>
            <label>
              <span className="mb-1 block font-medium">{tr("Short review (optional)")}</span>
              <textarea className="v2-input w-full" rows={2} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="outline" disabled={busy || stars < 1}>
                {tr("Save rating")}
              </Button>
              {mine ? (
                <Button type="button" variant="ghost" disabled={busy} onClick={remove}>
                  {tr("Remove my rating")}
                </Button>
              ) : null}
            </div>
          </form>
        </details>
      ) : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
    </div>
  );
}
