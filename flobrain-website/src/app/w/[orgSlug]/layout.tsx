import "@/styles/v2-tokens.css";

import { NotificationToaster } from "@/components/v2/shell/NotificationToaster";
import { WorkspaceShell } from "@/components/v2/shell/WorkspaceShell";
import { AccessProvider } from "@/lib/v2/AccessContext";
import { LayoutProvider } from "@/lib/v2/LayoutContext";
import { WorkspaceGuard } from "@/lib/v2/auth/WorkspaceGuard";

const RESERVED = new Set(["signin", "first-login", "reset-password", "sso"]);

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
      <AccessProvider orgSlug={orgSlug}>
        <LayoutProvider>
          <WorkspaceShell orgSlug={orgSlug}>{children}</WorkspaceShell>
          <NotificationToaster orgSlug={orgSlug} />
        </LayoutProvider>
      </AccessProvider>
    </WorkspaceGuard>
  );
}
