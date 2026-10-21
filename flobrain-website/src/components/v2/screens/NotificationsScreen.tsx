"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Row, Rows } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { v2Client } from "@/lib/v2/client";
import { describe, notificationsEmpty, unreadNotifications, type NotificationRow } from "@/lib/v2/screens/notifications";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function NotificationsScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const tr = useTr();
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const [loadState, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const fetchNow = useCallback(() => {
    if (!orgId) return;
    v2Client()
      .notifications(orgId)
      .then((payload) => {
        const next = (payload.results ?? []) as NotificationRow[];
        setRows(next);
        setState(notificationsEmpty(next) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError(tr("Could not load notifications"));
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId, tr]);

  // Until the workspace resolves, show its state. The first fetch starts in "loading"; setState runs only in callbacks.
  const state = orgState === "ready" ? loadState : orgState;

  const load = useCallback(() => {
    setState("loading");
    fetchNow();
  }, [fetchNow]);

  useEffect(() => {
    if (orgState === "ready") fetchNow();
  }, [orgState, fetchNow]);

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{tr("Notifications")}</h1>
        <Button
          type="button"
          variant="ghost"
          onClick={() => orgId && v2Client().readNotifications(orgId).then(load)}
        >
          {tr("Mark all read")}
        </Button>
      </div>
      <ScreenBody state={state} error={error || orgError} emptyLabel={tr("No notifications")} onRetry={load}>
        <Rows>
          {rows.map((row) => {
            const { text: template, vars, link } = describe(row);
            const text = tr(template, vars);
            const unread = unreadNotifications([row]).length > 0;
            return (
              <Row key={row.id}>
                {link ? (
                  <Link className={unread ? "font-medium underline-offset-2 hover:underline" : "hover:underline"} href={`/w/${orgSlug}/${link}`}>
                    {text}
                  </Link>
                ) : (
                  <span className={unread ? "font-medium" : ""}>{text}</span>
                )}
                {unread ? <Badge tone="accent">{tr("New")}</Badge> : null}
              </Row>
            );
          })}
        </Rows>
      </ScreenBody>
    </section>
  );
}
