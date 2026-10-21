"use client";

import { useEffect, useRef, useState } from "react";

import { DemoMention } from "@/components/v2/bridges/DemoMention";
import { LinkedPeople } from "@/components/v2/bridges/LinkedPeople";
import { installReturn, withoutInstallParams, type Overview } from "@/components/v2/bridges/logic";
import { MyAccounts } from "@/components/v2/bridges/MyAccounts";
import { SetupGuide } from "@/components/v2/bridges/SetupGuide";
import { WorkspacePanels } from "@/components/v2/bridges/WorkspacePanels";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

export default function BridgesSettingsPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const on = flag(access, "bridges");
  const { data, state, error, reload } = useOrgData<Overview>(orgId, on ? "/bridges" : null);
  const [version, setVersion] = useState(0);
  const [installMessage, setInstallMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const handled = useRef(false);

  const refresh = () => {
    reload();
    setVersion((v) => v + 1);
  };

  // Back from Slack: finish the install while signed in, then clean the address bar.
  useEffect(() => {
    if (!orgId || handled.current || typeof window === "undefined") return;
    const back = installReturn(window.location.search);
    if (!back) return;
    handled.current = true;
    window.history.replaceState(null, "", withoutInstallParams(window.location.href));
    const failures: Record<string, string> = {
      invalid_state: tr("That install link expired or was already used. Install again."),
      cancelled: tr("Slack install was cancelled."),
      not_configured: tr("Slack is not set up on this server yet."),
      exchange_failed: tr("Slack did not accept the install. Try again."),
    };
    const finish =
      back.result === "confirm" && back.code
        ? api.post(`/orgs/${orgId}/bridges/slack/confirm`, { code: back.code }).then(() => ({ kind: "ok" as const, text: tr("Slack is connected. Ask people to link their accounts.") }))
        : Promise.resolve({ kind: "error" as const, text: failures[back.result] ?? tr("Slack install failed.") });
    finish
      .catch((err) => ({ kind: "error" as const, text: errorText(err) }))
      .then((result) => {
        setInstallMessage(result);
        reload();
      });
  }, [orgId, tr, reload]);

  const manager = has(access, "bridges.manage") && !!data?.can_manage;
  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Slack and Teams")}
        intro={tr("Keep working in Slack or Microsoft Teams: ask your buddies there, get answers in the thread, and approve what they propose without leaving the chat.")}
      />
      <ScreenBody state={!access ? "loading" : !on ? "off" : state} error={error} onRetry={reload}>
        {orgId && data ? (
          <>
            {installMessage ? <Notice kind={installMessage.kind}>{installMessage.text}</Notice> : null}
            <MyAccounts orgId={orgId} data={data} onChange={refresh} />
            {data.demo ? <DemoMention orgId={orgId} workspaces={data.workspaces} /> : null}
            {manager ? <WorkspacePanels orgId={orgId} data={data} onChange={refresh} /> : null}
            {manager ? <LinkedPeople orgId={orgId} version={version} /> : null}
            {manager && data.setup ? <SetupGuide setup={data.setup} demo={data.demo} /> : null}
            {!manager ? <Notice>{tr("An admin connects Slack and Teams and chooses which buddy answers by default.")}</Notice> : null}
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
