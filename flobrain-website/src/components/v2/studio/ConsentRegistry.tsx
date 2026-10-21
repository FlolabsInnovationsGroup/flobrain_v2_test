"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { scopeLabel } from "./labels";
import type { Asset, Consent, Member } from "./model";

/** Consent records: yours, or everyone's with consent.manage. Revoking blocks posts that are not out yet. */
export function ConsentRegistry({ orgId }: { orgId: string | null }) {
  const tr = useTr();
  const { access } = useAccess();
  const manager = has(access, "consent.manage");
  const consents = useOrgData<Consent[]>(orgId, "/content/consents", { list: true });
  const members = useOrgData<{ results: Member[] }>(orgId, manager ? "/members?page_size=100" : null);
  const assets = useOrgData<Asset[]>(orgId, "/content/assets", { list: true });
  const [form, setForm] = useState({ scope: "public_social", who: "me", person: "", name: "", email: "", asset: "" });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const assetName = (id: string | null) => (id ? (rowsOf<Asset>(assets.data).find((a) => a.id === id)?.name ?? tr("One recording")) : tr("All recordings"));

  async function record() {
    setMessage(null);
    const body: Record<string, string> = { scope: form.scope };
    if (form.asset) body.media_asset = form.asset;
    if (form.who === "member" && form.person) body.person_user = form.person;
    if (form.who === "outside") {
      body.person_name = form.name;
      body.person_email = form.email;
    }
    try {
      await api.post(`/orgs/${orgId}/content/consents`, body);
      setMessage({ kind: "ok", text: tr("Consent recorded.") });
      setForm({ ...form, person: "", name: "", email: "" });
      consents.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function revoke(c: Consent) {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/content/consents/${c.id}/revoke`);
      setMessage({ kind: "ok", text: tr("Consent revoked. Posts with this person are held until it is given again.") });
      consents.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div>
      <Section title={tr("Record consent")}>
        <form
          className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            record();
          }}
        >
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label={tr("Who")}>
              <select className="v2-input" value={form.who} onChange={(e) => setForm({ ...form, who: e.target.value })}>
                <option value="me">{tr("Me")}</option>
                {manager ? <option value="member">{tr("A member")}</option> : null}
                {manager ? <option value="outside">{tr("Someone outside the org")}</option> : null}
              </select>
            </Field>
            <Field label={tr("For")}>
              <select className="v2-input" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
                <option value="internal">{scopeLabel(tr, "internal")}</option>
                <option value="public_social">{scopeLabel(tr, "public_social")}</option>
                <option value="marketing">{scopeLabel(tr, "marketing")}</option>
              </select>
            </Field>
            {form.who === "member" ? (
              <Field label={tr("Member")}>
                <select className="v2-input" required value={form.person} onChange={(e) => setForm({ ...form, person: e.target.value })}>
                  <option value="">{tr("Choose a person")}</option>
                  {rowsOf<Member>(members.data).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.username || m.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {form.who === "outside" ? (
              <>
                <Field label={tr("Name")}>
                  <input className="v2-input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </Field>
                <Field label={tr("Email")}>
                  <input className="v2-input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </Field>
              </>
            ) : null}
            <Field label={tr("Recording")} hint={tr("Leave on all recordings for a blanket consent.")}>
              <select className="v2-input" value={form.asset} onChange={(e) => setForm({ ...form, asset: e.target.value })}>
                <option value="">{tr("All recordings")}</option>
                {rowsOf<Asset>(assets.data)
                  .filter((a) => a.kind !== "audio")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </Field>
          </div>
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("Public social posts include internal use; marketing includes both. Keep the signed form or message as evidence.")}
          </p>
          <Button type="submit">{tr("Record consent")}</Button>
        </form>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      </Section>
      <Section title={manager ? tr("Everyone's consent") : tr("Your consent")}>
        <ScreenBody state={consents.state} error={consents.error} emptyLabel={tr("No consent recorded yet.")} onRetry={consents.reload}>
          <Rows>
            {rowsOf<Consent>(consents.data).map((c) => (
              <Row key={c.id}>
                <div>
                  <p className="font-medium">{c.person_name || tr("Unnamed person")}</p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {scopeLabel(tr, c.scope)} · {assetName(c.media_asset)} ·{" "}
                    {c.revoked_at ? tr("Revoked {when}", { when: when(c.revoked_at) }) : tr("Given {when}", { when: when(c.granted_at) })}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {c.revoked_at ? <Badge tone="bad">{tr("Revoked")}</Badge> : <Badge tone="good">{tr("Active")}</Badge>}
                  {!c.revoked_at && (manager || c.person_user === access?.user_id) ? (
                    <Button variant="danger" onClick={() => revoke(c)}>
                      {tr("Revoke")}
                    </Button>
                  ) : null}
                </div>
              </Row>
            ))}
          </Rows>
        </ScreenBody>
      </Section>
    </div>
  );
}
