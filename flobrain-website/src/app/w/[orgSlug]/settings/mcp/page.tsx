"use client";

import { useParams } from "next/navigation";

import { CallLog } from "@/components/v2/mcp/CallLog";
import { ConnectedApps } from "@/components/v2/mcp/ConnectedApps";
import { EndpointCard } from "@/components/v2/mcp/EndpointCard";
import { ServerGovernance } from "@/components/v2/mcp/ServerGovernance";
import type { Overview } from "@/components/v2/mcp/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

/** MCP hub: apps connected to FloBrain, your MCP endpoint, rules for outside MCP servers, the call log. */
export default function McpSettingsPage() {
  const tr = useTr();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId, access } = useAccess();
  const { data, state, error, reload } = useOrgData<Overview>(orgId, "/mcp/overview");
  const manager = has(access, "mcp.manage") || !!data?.can_manage;

  return (
    <div className="mx-auto w-full max-w-5xl p-4 sm:p-6">
      <PageHeader
        title={tr("MCP and tools")}
        intro={tr("Connect Claude, ChatGPT and other AI apps to FloBrain, and decide which outside tools your buddies may use.")}
      />
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data && orgId ? (
          <>
            <Section title={tr("Your MCP endpoint")}>
              <EndpointCard overview={data} />
            </Section>
            <Section title={tr("Apps connected to FloBrain")}>
              <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                {manager
                  ? tr("Everyone's connected apps in this organization. Disconnecting stops the app at once.")
                  : tr("Apps you connected. Disconnecting stops the app at once.")}
              </p>
              <ConnectedApps orgId={orgId} manager={manager} />
            </Section>
            {manager ? (
              <>
                <Section title={tr("Outside MCP servers")}>
                  <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
                    {tr("Rules for the outside servers your buddies can call. Every call still waits for the person's approval.")}
                  </p>
                  <ServerGovernance orgId={orgId} orgSlug={orgSlug} />
                </Section>
                <Section title={tr("Call log")}>
                  <CallLog orgId={orgId} />
                </Section>
              </>
            ) : null}
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
