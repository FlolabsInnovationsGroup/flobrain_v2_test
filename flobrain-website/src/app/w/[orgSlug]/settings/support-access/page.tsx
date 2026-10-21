"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Session = {
  id: string;
  user: { email: string };
  admin: { email: string };
  reason?: string;
  created_at: string;
  expires_at: string;
  live: boolean;
};

export default function SupportAccessPage() {
  const tr = useTr();
  const { orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<Session[]>(orgId, "/impersonations", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function end(id: string) {
    try {
      await api.post(`/orgs/${orgId}/impersonations/${id}/end`);
      setMessage({ kind: "ok", text: tr("Support access ended.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={tr("Support access")}
        intro={tr("When FloBrain support views your workspace as one of your people, it shows here with their reason. Sessions are read-only, last at most an hour, and you can end them.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("FloBrain support has never viewed your workspace.")} onRetry={reload}>
        <Rows>
          {rowsOf<Session>(data).map((s) => (
            <Row key={s.id} className="items-start">
              <div className="min-w-0">
                <p className="font-medium">
                  {tr("{admin} viewed as {user}", { admin: s.admin.email, user: s.user.email })}
                </p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("{start} until {end}. Reason: {reason}", { start: when(s.created_at), end: when(s.expires_at), reason: s.reason ?? "" })}
                </p>
              </div>
              {s.live ? (
                <Button variant="danger" onClick={() => end(s.id)}>
                  {tr("End now")}
                </Button>
              ) : (
                <Badge>{tr("Ended")}</Badge>
              )}
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </div>
  );
}
