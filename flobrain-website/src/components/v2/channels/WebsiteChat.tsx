"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { LOCALES, dirFor, useLocale, type V2Locale } from "@/i18n";
import { translate } from "@/i18n/phrases";

import { apiBase, loadToken, mergeMessages, parentOrigin, saveToken, type PublicConfig, type PublicMessage } from "./publicChat";

const POLL_MS = 4000;

function pickLocale(fallback: V2Locale): V2Locale {
  if (typeof window === "undefined") return fallback;
  const lang = new URLSearchParams(window.location.search).get("lang");
  return LOCALES.some((l) => l.code === lang) ? (lang as V2Locale) : fallback;
}

/** The customer's side of the website chat. Runs inside the widget's iframe or as its own page. */
export function WebsiteChat({ siteKey }: { siteKey: string }) {
  const userLocale = useLocale();
  const [locale, setLocale] = useState<V2Locale>(userLocale);
  const tr = useCallback((text: string, vars?: Record<string, string | number>) => translate(locale, text, vars), [locale]);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [failed, setFailed] = useState("");
  const [messages, setMessages] = useState<PublicMessage[]>([]);
  const [token, setToken] = useState("");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [framed, setFramed] = useState(false);
  const embed = useRef("");
  const listEnd = useRef<HTMLLIElement | null>(null);
  const base = `${apiBase()}/${encodeURIComponent(siteKey)}`;

  useEffect(() => {
    setLocale(pickLocale(userLocale));
    const claimed = new URLSearchParams(window.location.search).get("embed") ?? "";
    embed.current = parentOrigin(window, claimed);
    setFramed(window.self !== window.top);
    setToken(loadToken(siteKey));
    fetch(`${base}?embed=${encodeURIComponent(embed.current)}`)
      .then(async (res) => {
        if (res.status === 403) throw new Error("origin");
        if (!res.ok) throw new Error("missing");
        setConfig((await res.json()) as PublicConfig);
      })
      .catch((err: Error) => setFailed(err.message === "origin" ? "origin" : "missing"));
  }, [base, siteKey, userLocale]);

  const poll = useCallback(() => {
    if (!token) return;
    const params = new URLSearchParams({ conversation: token, embed: embed.current });
    fetch(`${base}/messages?${params}`)
      .then(async (res) => {
        if (res.status === 404) {
          saveToken(siteKey, "");
          setToken("");
          return;
        }
        if (res.ok) {
          const body = (await res.json()) as { messages: PublicMessage[] };
          setMessages((m) => mergeMessages(m, body.messages));
        }
      })
      .catch(() => undefined);
  }, [base, siteKey, token]);

  useEffect(() => {
    if (!token) return;
    poll();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") poll();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [token, poll]);

  useEffect(() => {
    listEnd.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    setError("");
    try {
      const res = await fetch(`${base}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value, conversation: token || undefined, embed_origin: embed.current }),
      });
      if (res.status === 429) throw new Error(tr("Too many messages. Wait a minute and try again."));
      if (!res.ok) throw new Error(tr("Your message was not sent. Try again."));
      const body = (await res.json()) as { conversation?: string; messages: PublicMessage[] };
      if (body.conversation) {
        saveToken(siteKey, body.conversation);
        setToken(body.conversation);
      }
      setMessages((m) => mergeMessages(m, body.messages));
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("Your message was not sent. Try again."));
    } finally {
      setSending(false);
    }
  }

  const close = () => window.parent?.postMessage({ type: "flobrain-chat-close" }, "*");
  const who = (m: PublicMessage) =>
    m.role === "customer" ? tr("You") : m.role === "staff" ? tr("Team") : m.role === "system" ? tr("Notice") : config?.name ?? tr("Assistant");

  return (
    <div className="v2-root flex h-dvh flex-col bg-[color:var(--fb-v2-bg)] text-[color:var(--fb-v2-text)]" dir={dirFor(locale)} lang={locale}>
      <header className="flex items-center justify-between gap-2 border-b border-[color:var(--fb-v2-border)] px-4 py-3">
        <div>
          <h1 className="text-base font-semibold">{config?.name ?? tr("Chat")}</h1>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("An AI assistant answers first. Ask for a person any time.")}
            {config?.demo ? ` ${tr("Demo")}` : ""}
          </p>
        </div>
        {framed ? (
          <button
            type="button"
            onClick={close}
            aria-label={tr("Close the chat")}
            className="rounded-full px-2 py-1 text-lg leading-none hover:bg-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]"
          >
            ×
          </button>
        ) : null}
      </header>
      {failed ? (
        <p role="alert" className="p-6 text-sm">
          {failed === "origin" ? tr("This chat is not available on this website.") : tr("This chat is not available right now.")}
        </p>
      ) : !config ? (
        <p role="status" className="p-6 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Loading…")}
        </p>
      ) : !config.embed_allowed ? (
        <p role="alert" className="p-6 text-sm">
          {tr("This chat is not available on this website.")}
        </p>
      ) : (
        <>
          <ul className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite" aria-label={tr("Messages")}>
            <li className="flex justify-start">
              <p className="max-w-[85%] rounded-xl bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm">{config.greeting}</p>
            </li>
            {messages.map((m) => (
              <li key={m.id} className={`flex ${m.role === "customer" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                    m.role === "customer" ? "bg-[color:var(--fb-v2-accent)] text-white" : m.role === "system" ? "bg-[color:var(--fb-v2-surface)] italic" : "bg-[color:var(--fb-v2-raised)]"
                  }`}
                >
                  <p className="sr-only">{who(m)}</p>
                  <p className="whitespace-pre-wrap">{m.text}</p>
                  {m.citations.length ? (
                    <p className="mt-1 text-xs opacity-80">
                      {tr("Sources:")} {m.citations.map((c) => `[${c.n}] ${c.title}`).join(", ")}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
            <li ref={listEnd} aria-hidden />
          </ul>
          {error ? (
            <p role="alert" className="px-4 text-sm text-[color:var(--fb-v2-error)]">
              {error}
            </p>
          ) : null}
          <form className="flex items-end gap-2 border-t border-[color:var(--fb-v2-border)] p-3" onSubmit={send}>
            <label className="flex-1">
              <span className="sr-only">{tr("Your message")}</span>
              <textarea
                className="v2-input max-h-32 min-h-11 w-full resize-none"
                rows={1}
                maxLength={2000}
                placeholder={tr("Write a message")}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(e);
                  }
                }}
              />
            </label>
            <button
              type="submit"
              disabled={sending || !text.trim()}
              className="rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[color:var(--fb-v2-accent-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--fb-v2-accent)] disabled:opacity-50"
            >
              {tr("Send")}
            </button>
          </form>
          <p className="px-4 pb-2 text-center text-[10px] text-[color:var(--fb-v2-text-faint)]">{tr("Powered by FloBrain")}</p>
        </>
      )}
    </div>
  );
}
