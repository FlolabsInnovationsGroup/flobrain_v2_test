"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Request = {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  preset_prompts: { label: string; prompt: string }[];
  allowed_tools: string[];
  allowed_sources: { mode?: string; rooms?: string[]; hidden_rooms?: number; source_types?: string[] };
  default_model: string | null;
  share_target: "team" | "org";
  share_team_name: string | null;
  requested_by: { id: string; name: string } | null;
  updated_at: string;
  hash: string;
};

const TOOLS: Record<string, string> = {
  "tasks.create": "Create tasks",
  "tasks.assign": "Assign tasks",
  "tasks.update_status": "Change task status",
  "rooms.post_message": "Post in rooms",
  "email.draft": "Draft emails",
  "meetings.create": "Schedule meetings",
  "reports.generate": "Generate team reports",
  "content.publish": "Submit social posts",
};
const SOURCES: Record<string, string> = {
  none: "No org knowledge",
  accessible: "Rooms and documents each person can open",
  rooms: "Only the rooms listed",
};

export function ShareRequestsScreen() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<Request[]>(orgId, "/buddies/share-requests", { list: true });
  const [rejecting, setRejecting] = useState<{ id: string; reason: string } | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function decide(row: Request, decision: "approve" | "reject", reason = "") {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/buddies/${row.id}/share/${decision}`, decision === "approve" ? { hash: row.hash } : { reason });
      setMessage({
        kind: "ok",
        text: decision === "approve" ? tr("{name} is shared now. {person} was told.", { name: row.name, person: row.requested_by?.name ?? tr("The requester") }) : tr("Request rejected. {person} was told.", { person: row.requested_by?.name ?? tr("The requester") }),
      });
      setRejecting(null);
      reload();
    } catch (err) {
      const e = apiError(err);
      setMessage({ kind: "error", text: e.code === "changed" ? tr("This buddy changed while you were reviewing it. Check it again before you decide.") : errorText(err) });
      if (e.code === "changed") reload();
    }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Buddy share requests")}
        intro={tr("A shared buddy answers each person only from what that person can open. Check its instructions and the actions it may propose before you approve.")}
        action={
          <Button asChild variant="ghost">
            <Link href={`/w/${orgSlug}/buddies`}>{tr("All buddies")}</Link>
          </Button>
        }
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("No share requests waiting for you.")} onRetry={reload}>
        <ul className="space-y-4">
          {rowsOf<Request>(data).map((row) => {
            const sources = row.allowed_sources ?? {};
            return (
              <li key={row.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-lg font-semibold">{row.name}</p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {row.share_target === "team"
                        ? tr("{person} wants to share it with {team}.", { person: row.requested_by?.name ?? tr("Someone"), team: row.share_team_name ?? tr("a team") })
                        : tr("{person} wants to share it with everyone in the organization.", { person: row.requested_by?.name ?? tr("Someone") })}{" "}
                      {tr("Last changed {when}.", { when: when(row.updated_at) })}
                    </p>
                  </div>
                  <Badge tone="waiting">{row.share_target === "team" ? tr("Team") : tr("Everyone")}</Badge>
                </div>
                {row.description ? <p className="mt-2">{row.description}</p> : null}
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-[10rem_1fr]">
                  <dt className="font-medium">{tr("Instructions")}</dt>
                  <dd>
                    {row.system_prompt ? (
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-[color:var(--fb-v2-border)] p-3 font-sans">{row.system_prompt}</pre>
                    ) : (
                      <span className="text-[color:var(--fb-v2-text-muted)]">{tr("None")}</span>
                    )}
                  </dd>
                  <dt className="font-medium">{tr("Knowledge")}</dt>
                  <dd>
                    {tr(SOURCES[sources.mode ?? "none"] ?? SOURCES.none)}
                    {sources.mode === "rooms"
                      ? ` (${tr("{n} room(s) you can open", { n: sources.rooms?.length ?? 0 })}${sources.hidden_rooms ? tr(", {n} you can't", { n: sources.hidden_rooms }) : ""})`
                      : ""}
                  </dd>
                  <dt className="font-medium">{tr("Actions it may propose")}</dt>
                  <dd>
                    {row.allowed_tools.length
                      ? row.allowed_tools.map((t) => (TOOLS[t] ? tr(TOOLS[t]) : t)).join(tr(", "))
                      : tr("None")}
                    {row.allowed_tools.length ? <span className="block text-[color:var(--fb-v2-text-muted)]">{tr("Every action still needs the person's own approval.")}</span> : null}
                  </dd>
                  {row.default_model ? (
                    <>
                      <dt className="font-medium">{tr("Model")}</dt>
                      <dd>{row.default_model}</dd>
                    </>
                  ) : null}
                  {row.preset_prompts.length ? (
                    <>
                      <dt className="font-medium">{tr("Quick prompts")}</dt>
                      <dd>{row.preset_prompts.map((p) => p.label).join(tr(", "))}</dd>
                    </>
                  ) : null}
                </dl>
                {rejecting?.id === row.id ? (
                  <form
                    className="mt-4"
                    onSubmit={(e) => {
                      e.preventDefault();
                      decide(row, "reject", rejecting.reason);
                    }}
                  >
                    <label className="block text-sm">
                      <span className="mb-1 block font-medium">{tr("Reason (optional, the requester sees it)")}</span>
                      <textarea className="v2-input min-h-16" maxLength={300} value={rejecting.reason} onChange={(e) => setRejecting({ id: row.id, reason: e.target.value })} />
                    </label>
                    <div className="mt-2 flex gap-2">
                      <Button type="submit" variant="danger">
                        {tr("Reject request")}
                      </Button>
                      <Button type="button" variant="ghost" onClick={() => setRejecting(null)}>
                        {tr("Cancel")}
                      </Button>
                    </div>
                  </form>
                ) : (
                  <div className="mt-4 flex gap-2">
                    <Button variant="waiting" onClick={() => decide(row, "approve")}>
                      {tr("Approve and share")}
                    </Button>
                    <Button variant="outline" onClick={() => setRejecting({ id: row.id, reason: "" })}>
                      {tr("Reject")}
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </ScreenBody>
    </div>
  );
}
