"use client";

import Link from "next/link";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { parseRows, type Kit, type Template } from "./model";
import { RenderQueue } from "./RenderQueue";

export function Templates({ orgId, orgSlug }: { orgId: string | null; orgSlug: string }) {
  const tr = useTr();
  const templates = useOrgData<Template[]>(orgId, "/content/templates", { list: true });
  const kits = useOrgData<Kit[]>(orgId, "/content/brand-kits", { list: true });
  const list = rowsOf<Template>(templates.data);
  const [form, setForm] = useState({ template: "", title: "", rows: "", kit: "" });
  const [batch, setBatch] = useState<{ project: string; renders: string[] } | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const chosen = list.find((t) => t.id === form.template) ?? list[0];
  const fields = Object.keys(chosen?.spec.variables ?? {});
  const rows = parseRows(form.rows, fields);

  async function run() {
    if (!chosen) return;
    setMessage(null);
    try {
      const res = await api.post<{ project: string; renders: string[] }>(`/orgs/${orgId}/content/batch`, {
        template: chosen.id,
        rows,
        title: form.title || undefined,
        brand_kit: form.kit || undefined,
      });
      setBatch(res);
      setMessage({ kind: "ok", text: tr("{n} videos queued, one per row.", { n: res.renders.length }) });
    } catch (err) {
      const e = apiError(err);
      setMessage({ kind: "error", text: e.code === "quota_exceeded" ? tr("Your org used its renders for this month ({details}).", { details: e.details }) : errorText(err) });
    }
  }

  return (
    <div>
      <ScreenBody state={templates.state} error={templates.error} emptyLabel={tr("No templates yet.")} onRetry={templates.reload}>
        <Rows>
          {list.map((t) => (
            <Row key={t.id}>
              <div>
                <p className="font-medium">{t.name}</p>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {t.spec.duration_seconds ? tr("{n} s", { n: t.spec.duration_seconds }) : ""}
                  {t.spec.resolution ? `, ${t.spec.resolution.join("×")}` : ""}
                  {t.spec.variables ? `. ${tr("Fields: {fields}", { fields: Object.keys(t.spec.variables).join(", ") })}` : ""}
                </p>
              </div>
              {t.builtin ? <Badge>{tr("Built in")}</Badge> : null}
            </Row>
          ))}
        </Rows>
      </ScreenBody>
      {chosen ? (
        <Section title={tr("Batch: one video per row")}>
          <form
            className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              run();
            }}
          >
            <div className="grid gap-x-4 sm:grid-cols-2">
              <Field label={tr("Template")}>
                <select className="v2-input" value={chosen.id} onChange={(e) => setForm({ ...form, template: e.target.value })}>
                  {list.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={tr("Brand kit")}>
                <select className="v2-input" value={form.kit} onChange={(e) => setForm({ ...form, kit: e.target.value })}>
                  <option value="">{tr("No brand kit")}</option>
                  {rowsOf<Kit>(kits.data).map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label={tr("Batch name")}>
              <input className="v2-input" maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder={tr("Batch: {name}", { name: chosen.name })} />
            </Field>
            <Field
              label={tr("Rows")}
              hint={
                fields.length > 1
                  ? tr("One video per line. Separate the fields with |, in this order: {fields}.", { fields: fields.join(", ") })
                  : tr("One video per line ({field}).", { field: fields[0] ?? "" })
              }
            >
              <textarea
                className="v2-input min-h-32"
                required
                value={form.rows}
                onChange={(e) => setForm({ ...form, rows: e.target.value })}
                placeholder={fields.length === 1 && fields[0] === "question" ? tr("What would you build with FloBrain?") : ""}
              />
            </Field>
            <Button type="submit" disabled={!rows.length}>
              {tr("Render {n} videos", { n: rows.length })}
            </Button>
          </form>
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
          {batch ? (
            <div className="mt-4">
              <p className="mb-2 text-sm">
                <Link className="underline" href={`/w/${orgSlug}/studio/${batch.project}`}>
                  {tr("Open the batch project")}
                </Link>
              </p>
              <RenderQueue orgId={orgId} path={`/content/projects/${batch.project}/render`} />
            </div>
          ) : null}
        </Section>
      ) : null}
    </div>
  );
}

export function BrandKits({ orgId }: { orgId: string | null }) {
  const tr = useTr();
  const { access } = useAccess();
  const manager = has(access, "content.manage");
  const kits = useOrgData<Kit[]>(orgId, "/content/brand-kits", { list: true });
  const [form, setForm] = useState({ name: "", primary: "#0E7C66", accent: "#F2B134", font: "", captionColor: "#FFFFFF", captionBg: "#000000", position: "bottom" });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function create() {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/content/brand-kits`, {
        name: form.name,
        colors: { primary: form.primary.toUpperCase(), accent: form.accent.toUpperCase() },
        fonts: form.font ? { heading: form.font } : {},
        caption_style: { color: form.captionColor.toUpperCase(), background: form.captionBg.toUpperCase(), position: form.position, font: form.font || undefined },
      });
      setMessage({ kind: "ok", text: tr("Brand kit created.") });
      setForm({ ...form, name: "" });
      kits.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div>
      <ScreenBody state={kits.state} error={kits.error} emptyLabel={tr("No brand kit yet.")} onRetry={kits.reload}>
        <ul className="grid gap-3 sm:grid-cols-2">
          {rowsOf<Kit>(kits.data).map((k) => (
            <li key={k.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
              <p className="font-semibold">{k.name}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(k.colors).map(([name, hex]) => (
                  <span key={name} className="flex items-center gap-1 text-xs">
                    <span className="inline-block h-5 w-5 rounded" style={{ background: hex }} aria-hidden />
                    {name} {hex}
                  </span>
                ))}
              </div>
              {Object.keys(k.fonts).length ? (
                <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Fonts: {fonts}", { fonts: Object.values(k.fonts).join(", ") })}</p>
              ) : null}
              {k.caption_style?.color ? (
                <p className="mt-3 inline-block rounded px-2 py-1 text-sm font-semibold" style={{ color: k.caption_style.color, background: k.caption_style.background || "rgba(0,0,0,0.6)" }}>
                  {tr("Caption style")}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </ScreenBody>
      {manager ? (
        <Section title={tr("New brand kit")}>
          <form
            className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              create();
            }}
          >
            <div className="grid gap-x-4 sm:grid-cols-2">
              <Field label={tr("Name")}>
                <input className="v2-input" required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label={tr("Heading font")}>
                <input className="v2-input" value={form.font} onChange={(e) => setForm({ ...form, font: e.target.value })} placeholder="Inter Display" />
              </Field>
              <Field label={tr("Primary colour")}>
                <input className="h-10 w-20" type="color" value={form.primary} onChange={(e) => setForm({ ...form, primary: e.target.value })} />
              </Field>
              <Field label={tr("Accent colour")}>
                <input className="h-10 w-20" type="color" value={form.accent} onChange={(e) => setForm({ ...form, accent: e.target.value })} />
              </Field>
              <Field label={tr("Caption text colour")}>
                <input className="h-10 w-20" type="color" value={form.captionColor} onChange={(e) => setForm({ ...form, captionColor: e.target.value })} />
              </Field>
              <Field label={tr("Caption background")}>
                <input className="h-10 w-20" type="color" value={form.captionBg} onChange={(e) => setForm({ ...form, captionBg: e.target.value })} />
              </Field>
              <Field label={tr("Caption position")}>
                <select className="v2-input" value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })}>
                  <option value="bottom">{tr("Bottom")}</option>
                  <option value="center">{tr("Middle")}</option>
                  <option value="top">{tr("Top")}</option>
                </select>
              </Field>
            </div>
            <Button type="submit">{tr("Create brand kit")}</Button>
          </form>
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        </Section>
      ) : null}
    </div>
  );
}
