"use client";

import Link from "next/link";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { ReadinessBar } from "./bits";
import { shortHash } from "./logic";
import type { PolicyRow, PolicyTemplate } from "./types";

export function PoliciesPanel({ orgId, orgSlug, canManage }: { orgId: string; orgSlug: string; canManage: boolean }) {
  const tr = useTr();
  const list = useOrgData<PolicyRow[]>(orgId, "/compliance/policies");
  const templates = useOrgData<PolicyTemplate[]>(orgId, "/compliance/policy-templates");
  const [picked, setPicked] = useState<string[]>([]);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const rows = list.data ?? [];
  const available = (templates.data ?? []).filter((t) => !t.installed);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      list.reload();
      templates.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Section title={tr("Policies")}>
        <ScreenBody state={list.state === "ready" && !rows.length ? "empty" : list.state} error={list.error} emptyLabel={tr("No policies yet. Install templates below, edit them, then publish.")} onRetry={list.reload}>
          <Rows>
            {rows.map((p) => {
              const share = p.stats.members ? (100 * p.stats.acknowledged) / p.stats.members : 0;
              return (
                <Row key={p.id}>
                  <div className="min-w-0 flex-1 basis-64">
                    {p.room_id && p.document_id ? (
                      <Link href={`/w/${orgSlug}/rooms/${p.room_id}/docs/${p.document_id}`} className="font-medium underline-offset-2 hover:underline">
                        {p.title}
                      </Link>
                    ) : (
                      <span className="font-medium">{p.title}</span>
                    )}
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {p.version ? tr("Version {n}, published {when}", { n: p.version, when: when(p.published_at) }) : tr("Draft, not published")}
                      {p.sha256 ? <span className="v2-mono ms-1" dir="ltr">· {shortHash(p.sha256)}</span> : null}
                    </p>
                    {p.version ? (
                      <div className="mt-2 flex max-w-sm items-center gap-2">
                        <ReadinessBar size="sm" value={share} label={tr("Acknowledged")} />
                        <span className="v2-mono shrink-0 text-xs">
                          {p.stats.acknowledged}/{p.stats.members}
                        </span>
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {p.draft_changed ? <Badge>{p.version ? tr("Edited since publishing") : tr("Draft")}</Badge> : <Badge tone="good">{tr("Published")}</Badge>}
                    {canManage && p.draft_changed ? (
                      <Button disabled={busy} onClick={() => run(() => api.post(`/orgs/${orgId}/compliance/policies/${p.id}/publish`), tr("Published. Members were asked to acknowledge it."))}>
                        {p.version ? tr("Publish new version") : tr("Publish")}
                      </Button>
                    ) : null}
                  </div>
                </Row>
              );
            })}
          </Rows>
        </ScreenBody>
      </Section>

      {canManage && available.length ? (
        <Section title={tr("Templates")}>
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("Starting points written for teams that use FloBrain. Installing one creates a document in the Security policies room. Edit it to fit how you work, then publish it.")}
          </p>
          <ul className="mb-3 grid gap-2 sm:grid-cols-2">
            {available.map((t) => (
              <li key={t.key}>
                <label className="flex h-full items-start gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-3 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={picked.includes(t.key)}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, t.key] : picked.filter((k) => k !== t.key))}
                  />
                  <span>
                    <span className="block font-medium">{t.title}</span>
                    <span className="block text-[color:var(--fb-v2-text-muted)]">{t.description}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <Button
            disabled={!picked.length || busy}
            onClick={() =>
              run(async () => {
                await api.post(`/orgs/${orgId}/compliance/policies`, { templates: picked });
                setPicked([]);
              }, tr("Installed as drafts. Edit them, then publish."))
            }
          >
            {tr("Install {n} templates", { n: picked.length })}
          </Button>
        </Section>
      ) : null}
    </>
  );
}
