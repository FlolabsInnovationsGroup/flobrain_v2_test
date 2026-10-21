import Link from "next/link";

export function RoomTabs({
  orgSlug,
  roomId,
  current,
}: {
  orgSlug: string;
  roomId: string;
  current: "chat" | "meetings" | "docs" | "tasks" | "calendar";
}) {
  const tabs = [
    { id: "chat", href: `/w/${orgSlug}/rooms/${roomId}`, label: "Chat" },
    { id: "meetings", href: `/w/${orgSlug}/rooms/${roomId}/meetings`, label: "Meetings" },
    { id: "docs", href: `/w/${orgSlug}/rooms/${roomId}/docs`, label: "Docs" },
    { id: "tasks", href: `/w/${orgSlug}/tasks?room=${roomId}`, label: "Tasks" },
    { id: "calendar", href: `/w/${orgSlug}/calendar?room=${roomId}`, label: "Calendar" },
  ] as const;
  return (
    <nav className="mb-4 flex gap-3 text-sm">
      {tabs.map((tab) => (
        <Link
          key={tab.id}
          href={tab.href}
          className={tab.id === current ? "font-semibold" : "text-[color:var(--fb-v2-text-muted)]"}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
