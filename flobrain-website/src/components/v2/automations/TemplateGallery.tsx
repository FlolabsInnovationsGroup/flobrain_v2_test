"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import type { RoomOption, Template } from "./types";

export function TemplateGallery({
  templates,
  rooms,
  canManage,
  onInstall,
}: {
  templates: Template[];
  rooms: RoomOption[];
  canManage: boolean;
  onInstall: (key: string, body: { room?: string; emails?: string[]; enabled: boolean }) => void;
}) {
  const tr = useTr();
  const [room, setRoom] = useState<Record<string, string>>({});
  const [emails, setEmails] = useState<Record<string, string>>({});
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {templates.map((t) => {
        const needsRoom = t.needs.includes("room");
        const needsEmails = t.needs.includes("emails");
        const list = (emails[t.key] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
        const ready = (!needsRoom || !!room[t.key]) && (!needsEmails || list.length > 0);
        return (
          <li key={t.key} className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-semibold">{t.name}</p>
              {t.proactive ? <Badge tone="accent">{tr("Proactive")}</Badge> : null}
              {t.installed ? <Badge tone="good">{tr("Added")}</Badge> : null}
            </div>
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{t.description}</p>
            {canManage && needsRoom ? (
              <label className="text-sm">
                <span className="mb-1 block text-xs font-medium text-[color:var(--fb-v2-text-muted)]">{tr("Room")}</span>
                <select className="v2-input w-full" value={room[t.key] ?? ""} onChange={(e) => setRoom((all) => ({ ...all, [t.key]: e.target.value }))}>
                  <option value="">{tr("Pick a room")}</option>
                  {rooms.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {canManage && needsEmails ? (
              <label className="text-sm">
                <span className="mb-1 block text-xs font-medium text-[color:var(--fb-v2-text-muted)]">{tr("Email addresses (separate with commas)")}</span>
                <input className="v2-input w-full" dir="ltr" value={emails[t.key] ?? ""} onChange={(e) => setEmails((all) => ({ ...all, [t.key]: e.target.value }))} />
              </label>
            ) : null}
            {canManage ? (
              <div className="mt-auto flex flex-wrap gap-2 pt-2">
                {t.proactive ? (
                  <Button disabled={!ready} onClick={() => onInstall(t.key, { enabled: true })}>
                    {tr("Turn on")}
                  </Button>
                ) : null}
                <Button
                  variant={t.proactive ? "outline" : "default"}
                  disabled={!ready}
                  onClick={() => onInstall(t.key, { room: room[t.key] || undefined, emails: needsEmails ? list : undefined, enabled: false })}
                >
                  {tr("Add and review")}
                </Button>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
