"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import type { Overview } from "./types";

/** Your MCP endpoint: the address to paste into Claude or ChatGPT, and plain steps for each. */
export function EndpointCard({ overview }: { overview: Overview }) {
  const tr = useTr();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function copy() {
    setError("");
    try {
      await navigator.clipboard.writeText(overview.endpoint);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setError(tr("Could not copy. Select the address and copy it yourself."));
    }
  }

  const steps: { app: string; items: string[] }[] = [
    {
      app: "Claude",
      items: [
        tr("In Claude, open Settings and find Connectors."),
        tr("Choose to add a custom connector, give it a name like FloBrain, and paste the address above."),
        tr("Claude opens a FloBrain page. Sign in, pick your organization and what Claude may do, then choose Allow."),
      ],
    },
    {
      app: "ChatGPT",
      items: [
        tr("In ChatGPT, open Settings and find Apps and connectors. Your admin may need to turn on custom connectors first."),
        tr("Create a connector, paste the address above, and choose OAuth as the sign-in method."),
        tr("ChatGPT opens a FloBrain page. Sign in, pick your organization and what ChatGPT may do, then choose Allow."),
      ],
    },
  ];

  return (
    <div className="flex flex-col gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <code
          dir="ltr"
          className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-[color:var(--fb-v2-page)] px-3 py-2 font-mono text-sm"
          aria-label={tr("Your MCP endpoint")}
        >
          {overview.endpoint}
        </code>
        <Button variant="outline" onClick={copy} aria-live="polite">
          {copied ? <Check aria-hidden className="me-1 size-4" /> : <Copy aria-hidden className="me-1 size-4" />}
          {copied ? tr("Copied") : tr("Copy address")}
        </Button>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Apps sign in with your FloBrain account. They see only what you can see, and anything they want to change waits for your approval.")}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {steps.map((s) => (
          <div key={s.app} className="rounded-lg bg-[color:var(--fb-v2-page)] p-3">
            <h3 className="mb-2 font-semibold">{tr("Add it to {app}", { app: s.app })}</h3>
            <ol className="list-decimal space-y-1 ps-5 text-sm">
              {s.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("For developers")}</summary>
        <dl className="mt-2 grid gap-1">
          <dt className="font-medium">{tr("Protected resource metadata")}</dt>
          <dd dir="ltr" className="break-all font-mono text-xs">{overview.resource_metadata}</dd>
          <dt className="font-medium">{tr("Authorization server metadata")}</dt>
          <dd dir="ltr" className="break-all font-mono text-xs">{overview.authorization_server}</dd>
          <dd className="text-[color:var(--fb-v2-text-muted)]">
            {tr("OAuth 2.1 with PKCE (S256) and dynamic client registration. Personal access tokens also work.")}
          </dd>
        </dl>
      </details>
    </div>
  );
}
