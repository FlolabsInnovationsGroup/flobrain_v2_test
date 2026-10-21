"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

type Policy = {
  inference_scope: "external_allowed" | "private_only";
  pii_redaction: string;
  data_region: string;
  self_hosted_hosts: string[];
  locked_private_only: boolean;
  pii_redaction_available: boolean;
  pii_detector: { name: string; basic: boolean } | null;
};

const REDACTION = [
  { key: "off", title: "Off", text: "Text is sent as written." },
  { key: "external_only", title: "When content leaves FloBrain", text: "Emails, phone numbers, card numbers and ID numbers are removed from what goes to external agents and outside services." },
  { key: "always", title: "Always", text: "The same removal, everywhere FloBrain supports it." },
] as const;

const CHOICES = [
  {
    key: "external_allowed",
    title: "Any approved AI provider",
    text: "FloBrain may send the text needed for an answer to the configured AI provider or to keys your members add.",
  },
  {
    key: "private_only",
    title: "Self-hosted models only",
    text: "Org content goes only to models you host. External providers and members' own keys are switched off. Features without a private model show as unavailable.",
  },
] as const;

export default function AiPolicyPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const { data, state, error, reload, setData } = useOrgData<Policy>(orgId, "/policy");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const canEdit = has(access, "policy.manage") && !data?.locked_private_only;

  async function redaction(value: string) {
    setMessage(null);
    try {
      const res = await api.put<Policy>(`/orgs/${orgId}/policy`, { pii_redaction: value });
      setData(res);
      setMessage({ kind: "ok", text: tr("Saved.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function choose(scope: string) {
    setMessage(null);
    try {
      const res = await api.put<Policy & { keys_disabled?: number }>(`/orgs/${orgId}/policy`, { inference_scope: scope });
      setData(res);
      setMessage({
        kind: "ok",
        text: scope === "private_only" ? tr("Saved. {n} external key(s) were switched off.", { n: res.keys_disabled ?? 0 }) : tr("Saved."),
      });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader title={tr("AI policy")} intro={tr("Where your organization's content may go when FloBrain uses AI.")} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data ? (
          <>
            {data.locked_private_only ? <Notice>{tr("This installation is locked to self-hosted models.")}</Notice> : null}
            {!has(access, "policy.manage") ? <Notice>{tr("Only the owner can change this.")}</Notice> : null}
            <div className="grid gap-3">
              {CHOICES.map((c) => {
                const active = data.inference_scope === c.key;
                return (
                  <div
                    key={c.key}
                    className={cn(
                      "rounded-xl bg-[color:var(--fb-v2-surface)] p-5 ring-1 ring-inset",
                      active ? "ring-[color:var(--fb-v2-accent)]" : "ring-[color:var(--fb-v2-border)]",
                    )}
                  >
                    <p className="font-semibold">
                      {tr(c.title)} {active ? <span className="text-sm font-normal text-[color:var(--fb-v2-accent)]">{tr("(current)")}</span> : null}
                    </p>
                    <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">{tr(c.text)}</p>
                    {canEdit && !active ? (
                      <Button className="mt-3" variant="outline" onClick={() => choose(c.key)}>
                        {tr("Use this")}
                      </Button>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <p className="mt-4 text-sm text-[color:var(--fb-v2-text-muted)]">
              {tr("Self-hosted model hosts: {hosts}.", { hosts: data.self_hosted_hosts.length ? data.self_hosted_hosts.join(", ") : tr("none set up on this server") })}
            </p>

            <h2 className="mb-2 mt-8 text-lg font-semibold">{tr("Personal data redaction")}</h2>
            {!data.pii_redaction_available ? (
              <Notice>{tr("No personal data detector is set up on this server, so redaction can't be turned on.")}</Notice>
            ) : data.pii_detector?.basic ? (
              <Notice>{tr("This server uses the basic pattern detector. It finds common formats only and misses names, addresses and anything unusual. Treat it as a safety net, not a guarantee.")}</Notice>
            ) : null}
            <div className="grid gap-2">
              {REDACTION.map((r) => {
                const active = data.pii_redaction === r.key;
                const usable = r.key === "off" || data.pii_redaction_available;
                return (
                  <label
                    key={r.key}
                    className={cn(
                      "flex items-start gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset",
                      active ? "ring-[color:var(--fb-v2-accent)]" : "ring-[color:var(--fb-v2-border)]",
                      !usable && "opacity-60",
                    )}
                  >
                    <input
                      type="radio"
                      name="pii_redaction"
                      className="mt-1"
                      checked={active}
                      disabled={!has(access, "policy.manage") || !usable}
                      onChange={() => redaction(r.key)}
                    />
                    <span>
                      <span className="font-medium">{tr(r.title)}</span>
                      <span className="block text-sm text-[color:var(--fb-v2-text-muted)]">{tr(r.text)}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
