"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { pollEvery, useLowBandwidth } from "@/lib/v2/LayoutContext";
import { v2Client } from "@/lib/v2/client";
import { describe, type NotificationRow } from "@/lib/v2/screens/notifications";

const EVERY_MS = 20000;
const SHOW_MS = 8000;

/**
 * New notifications pop up in the corner while FloBrain is open. In the demo (no push server),
 * they also show as a browser notification when the tab is in the background and the person
 * allowed notifications on the Notifications settings page.
 */
export function NotificationToaster({ orgSlug }: { orgSlug: string }) {
  const { orgId, access } = useAccess();
  const low = useLowBandwidth();
  const tr = useTr();
  const seen = useRef<Set<string> | null>(null);
  const [toasts, setToasts] = useState<NotificationRow[]>([]);
  const demo = !!access?.org.demo;

  useEffect(() => {
    if (!orgId) return;
    seen.current = null;
    let stopped = false;
    const poll = () => {
      if (document.hidden && !demo) return;
      v2Client()
        .notifications(orgId, true)
        .then((data) => {
          if (stopped) return;
          const rows = (data.results ?? []) as NotificationRow[];
          if (seen.current === null) {
            seen.current = new Set(rows.map((r) => r.id));
            return;
          }
          const fresh = rows.filter((r) => !seen.current!.has(r.id));
          fresh.forEach((r) => seen.current!.add(r.id));
          if (!fresh.length) return;
          setToasts((list) => [...fresh.slice(0, 3), ...list].slice(0, 3));
          if (demo && document.hidden && typeof Notification !== "undefined" && Notification.permission === "granted") {
            for (const r of fresh.slice(0, 3)) {
              const d = describe(r);
              new Notification("FloBrain", { body: tr(d.text, d.vars), tag: r.id });
            }
          }
        })
        .catch(() => undefined);
    };
    poll();
    const timer = window.setInterval(poll, pollEvery(EVERY_MS, low));
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [orgId, demo, tr, low]);

  useEffect(() => {
    if (!toasts.length) return;
    const timer = window.setTimeout(() => setToasts((list) => list.slice(0, -1)), SHOW_MS);
    return () => window.clearTimeout(timer);
  }, [toasts]);

  if (!toasts.length) return null;
  return (
    <div aria-live="polite" className="fixed bottom-4 end-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map((r) => {
        const d = describe(r);
        const text = tr(d.text, d.vars);
        return (
          <div key={r.id} className="rounded-xl bg-[color:var(--fb-v2-raised)] p-3 text-sm shadow-lg ring-1 ring-[color:var(--fb-v2-border)]">
            <div className="flex items-start justify-between gap-2">
              {d.link ? (
                <Link href={`/w/${orgSlug}/${d.link}`} className="font-medium hover:underline" onClick={() => setToasts((l) => l.filter((x) => x.id !== r.id))}>
                  {text}
                </Link>
              ) : (
                <span className="font-medium">{text}</span>
              )}
              <button type="button" aria-label={tr("Dismiss")} className="text-[color:var(--fb-v2-text-muted)]" onClick={() => setToasts((l) => l.filter((x) => x.id !== r.id))}>
                ×
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
