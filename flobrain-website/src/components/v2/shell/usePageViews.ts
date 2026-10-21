"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { api } from "@/lib/v2/api";
import { screenFor } from "@/lib/v2/screens/people";

const FLUSH_MS = 10000;

/**
 * Product analytics (Phase 0): one ``page.viewed`` per main screen visit, as a path shape such as
 * ``/rooms/:id`` (no org, ids or query strings). Nothing is sent when the person turned product
 * analytics off on the privacy page; the server drops such events too. Sent in small batches.
 */
export function usePageViews(orgId: string | null, orgSlug: string, demo: boolean) {
  const pathname = usePathname() || "";
  const consent = useRef<boolean | null>(null);
  const queue = useRef<string[]>([]);
  const last = useRef<string>("");

  useEffect(() => {
    if (!orgId) return;
    let cancelled = false;
    consent.current = null;
    api
      .get<{ settings?: { consents?: Record<string, boolean> } }>(`/orgs/${orgId}/me/privacy`)
      .then((value) => {
        if (!cancelled) consent.current = value.settings?.consents?.product_analytics !== false;
      })
      .catch(() => {
        if (!cancelled) consent.current = true; // the server still checks consent on every event
      });
    const flush = () => {
      if (!queue.current.length || consent.current === false) {
        if (consent.current === false) queue.current = [];
        return;
      }
      if (consent.current === null) return; // wait until we know
      const events = queue.current.splice(0, 20).map((page) => ({ name: "page.viewed", properties: { page, ...(demo ? { source: "demo" } : {}) } }));
      void api.post(`/orgs/${orgId}/events`, { events }).catch(() => undefined);
    };
    const timer = window.setInterval(flush, FLUSH_MS);
    const onHide = () => document.visibilityState === "hidden" && flush();
    document.addEventListener("visibilitychange", onHide);
    return () => {
      cancelled = true;
      flush();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onHide);
    };
  }, [orgId, demo]);

  useEffect(() => {
    const screen = screenFor(pathname, orgSlug);
    if (!screen || screen === last.current) return;
    last.current = screen;
    queue.current.push(screen);
  }, [pathname, orgSlug]);
}
