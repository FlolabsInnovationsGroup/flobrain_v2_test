"use client";

import { useEffect, useState } from "react";

import { StatusView, type StatusData } from "@/components/v2/platform/StatusView";
import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { apiError } from "@/lib/v2/api";
import { getApiBaseUrl } from "@/lib/axios";
import "@/styles/v2-tokens.css";

/**
 * Public status page. In production it reads the static file written by
 * ``manage.py export_status`` from separate hosting (``NEXT_PUBLIC_STATUS_JSON_URL``), so it stays
 * up when the API is down; otherwise it reads ``GET /api/public/status``.
 */
const STATIC_URL = process.env.NEXT_PUBLIC_STATUS_JSON_URL || "";

/** Messages by key, so the effect below does not depend on the language. */
const NOTES = {
  confirmed: "You will get an email when FloBrain has an incident.",
  usedLink: "This link was already used or is not valid.",
  failed: "Something went wrong. Try again later.",
  unsubscribed: "You will not get status emails any more.",
  checkInbox: "Check your inbox for a link to confirm.",
  badEmail: "Enter a valid email address.",
  tooMany: "Too many requests. Try again in a minute.",
} as const;
type NoteKey = keyof typeof NOTES;

async function post(path: string, body: unknown) {
  const res = await fetch(`${getApiBaseUrl()}/api/public/status${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw { response: { status: res.status, data } };
  return data as { unsubscribe?: string };
}

export default function StatusPage() {
  const locale = useLocale();
  const tr = useTr();
  const [data, setData] = useState<StatusData | null>(null);
  const [failed, setFailed] = useState(false);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState<{ kind: "ok" | "error" | "info"; key: NoteKey } | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(STATIC_URL || `${getApiBaseUrl()}/api/public/status`, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
        .then((value: StatusData) => {
          if (!alive) return;
          setData(value);
          setFailed(false);
        })
        .catch(() => alive && setFailed(true));
    load();
    const timer = window.setInterval(load, 60_000);
    // Links from the emails: ?confirm=… or ?unsubscribe=…
    const params = new URLSearchParams(window.location.search);
    const confirm = params.get("confirm");
    const unsubscribe = params.get("unsubscribe");
    if (confirm) {
      post("/confirm", { token: confirm })
        .then(() => alive && setNote({ kind: "ok", key: "confirmed" }))
        .catch((err) => alive && setNote({ kind: "error", key: apiError(err).status === 404 ? "usedLink" : "failed" }));
    } else if (unsubscribe) {
      post("/unsubscribe", { token: unsubscribe })
        .then(() => alive && setNote({ kind: "ok", key: "unsubscribed" }))
        .catch(() => alive && setNote({ kind: "error", key: "failed" }));
    }
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  async function subscribe() {
    setNote(null);
    try {
      await post("/subscribe", { email });
      setNote({ kind: "ok", key: "checkInbox" });
      setEmail("");
    } catch (err) {
      const e = apiError(err);
      setNote({ kind: "error", key: e.status === 400 ? "badEmail" : e.status === 429 ? "tooMany" : "failed" });
    }
  }

  return (
    <div className="v2-root min-h-dvh p-6" dir={dirFor(locale)}>
      <main className="mx-auto w-full max-w-3xl">
        <h1 className="mb-1 text-3xl font-semibold tracking-tight">{tr("FloBrain status")}</h1>
        <p className="mb-6 text-[color:var(--fb-v2-text-muted)]">{tr("Whether FloBrain is working, and what we are doing when it is not.")}</p>
        {note ? <Notice kind={note.kind}>{tr(NOTES[note.key])}</Notice> : null}
        {data ? (
          <StatusView data={data} />
        ) : failed ? (
          <p role="alert">{tr("The status could not be loaded. Try again in a minute.")}</p>
        ) : (
          <p role="status">{tr("Loading status…")}</p>
        )}
        {failed && data ? <Notice>{tr("Showing the last status we could load.")}</Notice> : null}
        <section className="mt-10 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
          <h2 className="font-semibold">{tr("Get incident emails")}</h2>
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("We email you when an incident starts, changes or ends. Every email has a link to stop them.")}</p>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              subscribe();
            }}
          >
            <label className="sr-only" htmlFor="status-email">
              {tr("Email")}
            </label>
            <input id="status-email" className="v2-input w-72" type="email" required placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            <Button type="submit">{tr("Subscribe")}</Button>
          </form>
        </section>
      </main>
    </div>
  );
}
