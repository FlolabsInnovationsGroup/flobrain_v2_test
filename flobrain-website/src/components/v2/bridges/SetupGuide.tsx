"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import type { SetupStatus } from "./logic";

export function Copyable({ label, value }: { label: string; value: string }) {
  const tr = useTr();
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2">
      <p className="text-xs font-medium">{label}</p>
      <div className="mt-1 flex flex-wrap items-start gap-2">
        <code className="block min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-[color:var(--fb-v2-raised)] p-2 text-xs" dir="ltr">
          {value}
        </code>
        <Button
          variant="outline"
          onClick={() =>
            void navigator.clipboard?.writeText(value).then(
              () => setCopied(true),
              () => setCopied(false),
            )
          }
        >
          {copied ? tr("Copied") : tr("Copy")}
        </Button>
      </div>
    </div>
  );
}

function Missing({ names }: { names: string[] }) {
  const tr = useTr();
  if (!names.length) return null;
  return (
    <p className="mt-2 text-sm">
      {tr("The server still needs:")}{" "}
      <span dir="ltr" className="font-mono text-xs">
        {names.join(", ")}
      </span>
    </p>
  );
}

/** What has to exist outside FloBrain before Slack or Teams can work, in plain words. */
export function SetupGuide({ setup, demo }: { setup: SetupStatus; demo: boolean }) {
  const tr = useTr();
  const e = setup.endpoints;
  return (
    <Section title={tr("Platform setup")}>
      {demo ? (
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Demo mode: Slack and Teams are simulated. Nothing below is needed to try them here.")}
        </p>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold">{tr("Slack app")}</p>
            <Badge tone={setup.slack.ready ? "good" : "neutral"}>{setup.slack.ready ? tr("Ready") : tr("Needs setup")}</Badge>
          </div>
          <ol className="mt-2 list-decimal space-y-1 ps-5 text-sm">
            <li>{tr("Create a Slack app from the FloBrain manifest (in the Bridges guide).")}</li>
            <li>{tr("Put its client ID, client secret and signing secret in the server settings.")}</li>
            <li>{tr("Paste these addresses in the Slack app, then install it here.")}</li>
          </ol>
          <Missing names={setup.slack.missing} />
          <Copyable label={tr("Event subscriptions request URL")} value={e.slack_events} />
          <Copyable label={tr("Slash command /flo request URL")} value={e.slack_commands} />
          <Copyable label={tr("Interactivity request URL")} value={e.slack_interactions} />
          <Copyable label={tr("OAuth redirect URL")} value={e.slack_redirect} />
        </div>
        <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold">{tr("Azure bot for Teams")}</p>
            <Badge tone={setup.teams.ready ? "good" : "neutral"}>{setup.teams.ready ? tr("Ready") : tr("Needs setup")}</Badge>
          </div>
          <ol className="mt-2 list-decimal space-y-1 ps-5 text-sm">
            <li>{tr("Register an Azure Bot and turn on its Microsoft Teams channel.")}</li>
            <li>{tr("Put the bot's app ID and client secret in the server settings.")}</li>
            <li>{tr("Set the bot's messaging endpoint to this address, then connect your tenant here.")}</li>
            <li>{tr("Upload the Teams app (manifest below) in the Teams admin center.")}</li>
          </ol>
          <Missing names={setup.teams.missing} />
          {setup.teams.jwt_library === false ? <p className="mt-2 text-sm text-[color:var(--fb-v2-error)]">{tr("The server is missing PyJWT, so Teams messages can't be checked.")}</p> : null}
          <Copyable label={tr("Messaging endpoint")} value={e.teams_messages} />
        </div>
      </div>
      {setup.encryption === false ? <p className="mt-3 text-sm text-[color:var(--fb-v2-error)]">{tr("Encryption is not configured on this server, so Slack can't be installed.")}</p> : null}
    </Section>
  );
}
