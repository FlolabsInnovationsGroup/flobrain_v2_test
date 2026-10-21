import "@/styles/v2-tokens.css";

import Link from "next/link";

import { RoomsSidebar } from "@/components/v2/screens/RoomsSidebar";
import { ToolsRail } from "@/components/v2/screens/ToolsRail";
import { WorkspaceHeader } from "@/components/v2/screens/WorkspaceHeader";
import { WorkspaceGuard } from "@/lib/v2/auth/WorkspaceGuard";

const RESERVED = new Set(["signin", "first-login", "reset-password"]);

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ orgSlug: string }>;
}) {
  const { orgSlug } = await params;
  if (RESERVED.has(orgSlug)) {
    return children;
  }
  return (
    <WorkspaceGuard>
      <div className="flex min-h-dvh">
        <nav className="flex w-14 flex-col items-center gap-3 border-e border-[color:var(--fb-v2-border)] py-4 text-sm">
          <Link href={`/w/${orgSlug}`} className="text-lg font-semibold">
            F
          </Link>
          <Link href={`/w/${orgSlug}/search`}>S</Link>
          <Link href={`/w/${orgSlug}/notifications`}>N</Link>
          <Link href={`/w/${orgSlug}/tools`}>T</Link>
          <Link href={`/w/${orgSlug}/tasks`}>K</Link>
        </nav>
        <RoomsSidebar orgSlug={orgSlug} />
        <div className="flex min-w-0 flex-1 flex-col">
          <WorkspaceHeader orgSlug={orgSlug} />
          <div className="flex min-h-0 flex-1">
            <main className="min-w-0 flex-1 p-4">{children}</main>
            <ToolsRail orgSlug={orgSlug} />
          </div>
        </div>
      </div>
    </WorkspaceGuard>
  );
}
