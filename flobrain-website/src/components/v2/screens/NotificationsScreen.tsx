"use client";

import { useCallback, useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { v2Client } from "@/lib/v2/client";
import { notificationsEmpty, unreadNotifications, type NotificationRow } from "@/lib/v2/screens/notifications";
import { screenStateFromHttp, type ScreenState } from "@/lib/v2/screens/status";
import { useWorkspaceOrg } from "@/lib/v2/useWorkspaceOrg";

export function NotificationsScreen({ orgSlug }: { orgSlug: string }) {
  const { orgId, state: orgState, error: orgError } = useWorkspaceOrg(orgSlug);
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    setState("loading");
    v2Client()
      .notifications(orgId)
      .then((payload) => {
        const next = (payload.results ?? []) as NotificationRow[];
        setRows(next);
        setState(notificationsEmpty(next) ? "empty" : "ready");
      })
      .catch((err: { response?: { status?: number } }) => {
        setError("Could not load notifications");
        setState(screenStateFromHttp(err.response?.status ?? 500));
      });
  }, [orgId]);

  useEffect(() => {
    if (orgState === "ready") load();
    else setState(orgState);
  }, [orgState, load]);

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Notifications</h1>
        <Button
          type="button"
          variant="ghost"
          onClick={() => orgId && v2Client().readNotifications(orgId).then(load)}
        >
          Mark all read
        </Button>
      </div>
      <ScreenBody state={state} error={error || orgError} emptyLabel="No notifications" onRetry={load}>
        <ul className="space-y-2">
          {rows.map((row) => (
            <li key={row.id}>
              {row.kind}
              {unreadNotifications([row]).length ? " · unread" : ""}
            </li>
          ))}
        </ul>
      </ScreenBody>
    </section>
  );
}
