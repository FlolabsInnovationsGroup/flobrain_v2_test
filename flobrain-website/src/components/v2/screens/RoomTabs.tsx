"use client";

import Link from "next/link";

import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";

export function RoomTabs({
  orgSlug,
  roomId,
  current,
}: {
  orgSlug: string;
  roomId: string;
  current: "chat" | "ai" | "meetings" | "docs" | "tasks" | "calendar";
}) {
  const tr = useTr();
  const { access } = useAccess();
  const showAI = flag(access, "room_ai") && has(access, "ai.use");
  const tabs = [
    { id: "chat", href: `/w/${orgSlug}/rooms/${roomId}`, label: "Chat" },
    ...(showAI || current === "ai" ? [{ id: "ai", href: `/w/${orgSlug}/rooms/${roomId}/ai`, label: "room tab|AI" }] : []),
    { id: "meetings", href: `/w/${orgSlug}/rooms/${roomId}/meetings`, label: "Meetings" },
    { id: "docs", href: `/w/${orgSlug}/rooms/${roomId}/docs`, label: "Docs" },
    { id: "tasks", href: `/w/${orgSlug}/tasks?room=${roomId}`, label: "Tasks" },
    { id: "calendar", href: `/w/${orgSlug}/calendar?room=${roomId}`, label: "Calendar" },
  ];
  return (
    <nav className="mb-4 flex flex-wrap gap-3 text-sm">
      {tabs.map((tab) => (
        <Link
          key={tab.id}
          href={tab.href}
          aria-current={tab.id === current ? "page" : undefined}
          className={tab.id === current ? "font-semibold" : "text-[color:var(--fb-v2-text-muted)]"}
        >
          {tr(tab.label)}
        </Link>
      ))}
    </nav>
  );
}
