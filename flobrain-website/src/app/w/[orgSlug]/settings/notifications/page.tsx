"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader, Row, Rows } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { play, SOUNDS } from "@/lib/v2/sounds";
import { useOrgData } from "@/lib/v2/useOrgData";

type Pref = { type: string; enabled: boolean; push: boolean; sound: string };

const LABELS: Record<string, string> = {
  direct_message: "Direct messages",
  team_chat_message: "Team room messages",
  project_chat_message: "Project room messages",
  task_assigned: "A task is assigned to you",
  task_deadline_reached: "A task reaches its due date",
  meeting_started: "A meeting starts",
  announcement: "Announcements",
  ai_response: "AI answers",
  action_proposed: "AI proposes an action",
  permission_request: "Permission requests",
  publish_failed: "A post failed to publish",
  render_finished: "A video render finished",
  budget_alert: "AI budget alerts",
  agent_paused: "An agent was paused",
  impersonation_started: "FloBrain support viewed your workspace",
};

function b64ToBytes(base64: string) {
  const pad = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export default function NotificationSettingsPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const { data, state, error, reload, setData } = useOrgData<Pref[]>(orgId, "/me/notification-preferences", { orgScoped: false });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function change(type: string, patch: Partial<Pref>) {
    try {
      const row = await api.put<Pref>("/me/notification-preferences", { type, ...patch });
      setData(rowsOf<Pref>(data).map((p) => (p.type === type ? row : p)));
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function enablePush() {
    setMessage(null);
    try {
      const { public_key } = await api.get<{ public_key: string }>("/push/vapid-public-key");
      if (!public_key && access?.org.demo && typeof Notification !== "undefined") {
        // The demo has no push server: allow notifications from this tab instead.
        const allowed = await Notification.requestPermission();
        if (allowed !== "granted") throw new Error(tr("Notifications are blocked for this site in your browser settings."));
        setMessage({ kind: "ok", text: tr("Demo: new notifications show on this device while FloBrain is open in a tab.") });
        return;
      }
      if (!public_key) throw new Error(tr("Push is not set up on this server yet."));
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error(tr("This browser can't receive push notifications."));
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error(tr("Notifications are blocked for this site in your browser settings."));
      const reg = await navigator.serviceWorker.register("/sw.js");
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) });
      await api.post("/me/push-subscriptions", sub.toJSON());
      setMessage({ kind: "ok", text: tr("Push is on for this device.") });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error && !("response" in err) ? err.message : errorText(err) });
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={tr("Notification settings")}
        intro={tr("Choose what reaches you, and how it sounds. Push notifications show who wrote, never the message itself.")}
        action={<Button onClick={enablePush}>{tr("Turn on push for this device")}</Button>}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        <Rows>
          {rowsOf<Pref>(data).map((p) => {
            const label = LABELS[p.type] ? tr(LABELS[p.type]) : p.type;
            return (
              <Row key={p.type}>
                <label className="flex min-w-0 flex-1 items-center gap-3">
                  <input type="checkbox" checked={p.enabled} onChange={(e) => change(p.type, { enabled: e.target.checked })} />
                  <span>{label}</span>
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={p.push} disabled={!p.enabled} onChange={(e) => change(p.type, { push: e.target.checked })} />
                  {tr("Push")}
                </label>
                <div className="flex items-center gap-1">
                  <select
                    className="v2-input w-28 py-1"
                    aria-label={tr("Sound for {label}", { label })}
                    value={p.sound}
                    disabled={!p.enabled}
                    onChange={(e) => change(p.type, { sound: e.target.value })}
                  >
                    {Object.entries(SOUNDS).map(([key, s]) => (
                      <option key={key} value={key}>
                        {tr(s.label)}
                      </option>
                    ))}
                  </select>
                  <Button variant="ghost" aria-label={tr("Play sound")} onClick={() => play(p.sound)}>
                    ▶
                  </Button>
                </div>
              </Row>
            );
          })}
        </Rows>
      </ScreenBody>
    </div>
  );
}
