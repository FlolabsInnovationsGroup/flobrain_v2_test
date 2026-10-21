"use client";

import { ConnectionsPanel } from "@/components/v2/channels/ConnectionsPanel";
import { CustomerSettingsPanel } from "@/components/v2/channels/CustomerSettingsPanel";
import { DemoSimulator } from "@/components/v2/channels/DemoSimulator";
import { LinkMyPhone } from "@/components/v2/channels/LinkMyPhone";
import type { Connection, Linkable } from "@/components/v2/channels/logic";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

export default function ChannelsSettingsPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const manager = has(access, "channels.manage");
  const on = flag(access, "channels");
  const demo = !!access?.org.demo;
  const canCustomers = flag(access, "customer_buddy") && (manager || has(access, "customers.reply"));
  const { data: managed } = useOrgData<Connection[]>(orgId, on && demo && manager ? "/channels/connections" : null);
  const { data: mine } = useOrgData<{ connections: Linkable[] }>(orgId, on && demo && !manager ? "/channels/links" : null);
  const options = manager ? rowsOf<Connection>(managed) : (mine?.connections ?? []);

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Channels")}
        intro={tr("Reach your buddies from WhatsApp and Telegram, and let the customer buddy answer customers on your website and WhatsApp.")}
      />
      <ScreenBody state={!access ? "loading" : on ? "ready" : "off"}>
        {orgId ? (
          <>
            {has(access, "ai.use") ? <LinkMyPhone orgId={orgId} /> : null}
            {manager ? <ConnectionsPanel orgId={orgId} demo={demo} /> : null}
            {manager && flag(access, "customer_buddy") ? <CustomerSettingsPanel orgId={orgId} /> : null}
            {!manager ? <Notice>{tr("An admin connects WhatsApp, Telegram and the website chat.")}</Notice> : null}
            {demo ? <DemoSimulator orgId={orgId} orgSlug={access?.org.slug ?? ""} connections={options} canCustomers={canCustomers} /> : null}
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
