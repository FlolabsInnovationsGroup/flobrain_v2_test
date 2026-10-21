"use client";

import { Briefcase, CalendarClock, Compass, MessageCircle, Sparkles, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

export type CrewTemplate = {
  key: string;
  slug: string;
  name: string;
  description: string;
  icon: string;
  gradient: string;
  starter_prompts: string[];
  channel_only: boolean;
  installed: boolean;
  buddy: string | null;
};
type TemplateList = { flo: { id: string; name: string; enabled: boolean }; can_install: boolean; templates: CrewTemplate[] };

const ICONS: Record<string, LucideIcon> = { briefcase: Briefcase, compass: Compass, calendar: CalendarClock, message: MessageCircle, sparkles: Sparkles };
export const FLO_GRADIENT = "linear-gradient(135deg,#7C6BFF,#CC34FF)";

/** A buddy's round badge: its icon on its gradient (the marketing site's look). */
export function CrewBadge({ icon, gradient, size = 40 }: { icon: string; gradient: string; size?: number }) {
  const Icon = ICONS[icon] ?? Sparkles;
  return (
    <span aria-hidden className="inline-flex shrink-0 items-center justify-center rounded-xl text-white" style={{ background: gradient, width: size, height: size }}>
      <Icon style={{ width: size * 0.5, height: size * 0.5 }} />
    </span>
  );
}

/** "Not sure who to ask? Ask Flo." A card that opens Flo's chat. */
export function AskFloHint({ orgSlug, floId }: { orgSlug: string; floId: string }) {
  const tr = useTr();
  return (
    <div className="mb-6 flex flex-wrap items-center gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset ring-[color:var(--fb-v2-accent-soft)]">
      <CrewBadge icon="sparkles" gradient={FLO_GRADIENT} />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{tr("Not sure who to ask? Ask Flo.")}</p>
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Flo hands your question to the right buddy and tells you who answered. It only uses buddies and sources you can open.")}
        </p>
      </div>
      <Button asChild>
        <Link href={`/w/${orgSlug}/buddies/${floId}`}>{tr("Ask Flo")}</Link>
      </Button>
    </div>
  );
}

/** Specialist buddies an admin can add for everyone. Hidden when the feature is off. */
export function CrewTemplates({ orgId, orgSlug, onInstalled }: { orgId: string | null; orgSlug: string; onInstalled?: () => void }) {
  const tr = useTr();
  const { data, state, reload } = useOrgData<TemplateList>(orgId, "/buddies/templates");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  if (state !== "ready" || !data) return null;

  async function install(t: CrewTemplate) {
    setBusy(t.key);
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/buddies/templates/${t.key}/install`);
      setMessage({ kind: "ok", text: tr("{name} is ready for everyone.", { name: tr(t.name) }) });
      reload();
      onInstalled?.();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy("");
    }
  }

  return (
    <Section title={tr("Templates")}>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {data.can_install
          ? tr("Specialist buddies you can add for everyone. Drafts and changes they suggest still wait for approval.")
          : tr("Specialist buddies an admin can add for everyone.")}
      </p>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.templates.map((t) => (
          <li key={t.key} className="flex h-full flex-col gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
            <span className="flex items-center gap-3">
              <CrewBadge icon={t.icon} gradient={t.gradient} />
              <span className="min-w-0">
                <span className="block font-semibold">{tr(t.name)}</span>
                {t.channel_only ? <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Used on the website chat and WhatsApp")}</span> : null}
              </span>
            </span>
            <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr(t.description)}</span>
            {t.starter_prompts[0] ? <span className="text-xs text-[color:var(--fb-v2-text-faint)]">{tr("Try: {prompt}", { prompt: tr(t.starter_prompts[0]) })}</span> : null}
            <span className="mt-auto flex flex-wrap items-center gap-2">
              {t.installed ? (
                <>
                  <Badge tone="good">{tr("Added")}</Badge>
                  {t.buddy && !t.channel_only ? (
                    <Link href={`/w/${orgSlug}/buddies/${t.buddy}`} className="text-sm font-medium underline">
                      {tr("Open")}
                    </Link>
                  ) : null}
                </>
              ) : data.can_install ? (
                <Button variant="outline" disabled={busy === t.key} onClick={() => install(t)}>
                  {busy === t.key ? tr("Adding…") : tr("Add for everyone")}
                </Button>
              ) : (
                <Badge>{tr("Not added")}</Badge>
              )}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
