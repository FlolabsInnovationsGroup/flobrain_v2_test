"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

import { ConsentRegistry } from "./ConsentRegistry";
import { ContentCalendar } from "./ContentCalendar";
import { projectStatus } from "./labels";
import { PLATFORM_LABEL, PLATFORMS, type Project, type PublishJob } from "./model";
import { PublishJobs } from "./PublishJobs";
import { RenderQueue } from "./RenderQueue";
import { SocialAccounts } from "./SocialAccounts";
import { BrandKits, Templates } from "./TemplatesAndKits";

const TABS = ["projects", "renders", "calendar", "posts", "accounts", "consent", "templates", "kits"] as const;
type Tab = (typeof TABS)[number];

export function StudioHub({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const router = useRouter();
  const params = useSearchParams();
  const { orgId, access } = useAccess();
  const initial = params.get("tab");
  const [tab, setTab] = useState<Tab>(TABS.includes(initial as Tab) ? (initial as Tab) : "projects");
  // Back from a social OAuth flow: read the one-time code once, then drop it from the address bar.
  const [returned] = useState(() => (params.get("result") ? { result: params.get("result") ?? "", confirm: params.get("confirm") ?? "" } : null));
  const publishing = flag(access, "social_publishing");

  useEffect(() => {
    if (returned) router.replace(`/w/${orgSlug}/studio?tab=accounts`, { scroll: false });
  }, [returned, router, orgSlug]);

  const labels: Record<Tab, string> = {
    projects: tr("Projects"),
    renders: tr("Render queue"),
    calendar: tr("Calendar"),
    posts: tr("Posts"),
    accounts: tr("Social accounts"),
    consent: tr("Consent"),
    templates: tr("Templates"),
    kits: tr("Brand kits"),
  };
  const shown = TABS.filter((t) => publishing || !["calendar", "posts", "accounts"].includes(t));

  function open(next: Tab) {
    setTab(next);
    router.replace(`/w/${orgSlug}/studio${next === "projects" ? "" : `?tab=${next}`}`, { scroll: false });
  }

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Content Studio")}
        intro={tr("Turn recordings into short videos in your brand. AI suggests cuts and copy; a person approves before anything is published, and everyone shown must have given consent.")}
        action={access?.org.demo ? <Badge tone="waiting">{tr("Demo")}</Badge> : undefined}
      />
      <div role="tablist" aria-label={tr("Content Studio")} className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--fb-v2-border)]">
        {shown.map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => open(name)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === name ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]",
            )}
          >
            {labels[name]}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "projects" ? <Projects orgId={orgId} orgSlug={orgSlug} /> : null}
        {tab === "renders" ? <RenderQueue orgId={orgId} path="/content/renders" showProject /> : null}
        {tab === "calendar" ? <ContentCalendar orgId={orgId} /> : null}
        {tab === "posts" ? <Posts orgId={orgId} /> : null}
        {tab === "accounts" ? <SocialAccounts orgId={orgId} returned={returned} /> : null}
        {tab === "consent" ? <ConsentRegistry orgId={orgId} /> : null}
        {tab === "templates" ? <Templates orgId={orgId} orgSlug={orgSlug} /> : null}
        {tab === "kits" ? <BrandKits orgId={orgId} /> : null}
      </div>
    </div>
  );
}

function Projects({ orgId, orgSlug }: { orgId: string | null; orgSlug: string }) {
  const tr = useTr();
  const router = useRouter();
  const projects = useOrgData<Project[]>(orgId, "/content/projects", { list: true });
  const [title, setTitle] = useState("");
  const [platforms, setPlatforms] = useState<string[]>(["youtube"]);
  const [message, setMessage] = useState<string | null>(null);

  async function create() {
    setMessage(null);
    try {
      const p = await api.post<Project>(`/orgs/${orgId}/content/projects`, { title, target_platforms: platforms });
      router.push(`/w/${orgSlug}/studio/${p.id}`);
    } catch (err) {
      setMessage(errorText(err));
    }
  }

  return (
    <>
      <form
        className="mb-6 flex flex-wrap items-end gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
        onSubmit={(e) => {
          e.preventDefault();
          create();
        }}
      >
        <label className="min-w-64 flex-1 text-sm">
          <span className="mb-1 block font-medium">{tr("New video")}</span>
          <input className="v2-input" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr("Launch teaser, 30 seconds")} />
        </label>
        <fieldset className="text-sm">
          <legend className="mb-1 font-medium">{tr("platforms|For")}</legend>
          {PLATFORMS.slice(0, 4).map((p) => (
            <label key={p} className="me-3 inline-flex items-center gap-1">
              <input type="checkbox" checked={platforms.includes(p)} onChange={(e) => setPlatforms(e.target.checked ? [...platforms, p] : platforms.filter((x) => x !== p))} />
              {PLATFORM_LABEL[p]}
            </label>
          ))}
        </fieldset>
        <Button type="submit">{tr("Create project")}</Button>
      </form>
      {message ? <Notice kind="error">{message}</Notice> : null}
      <ScreenBody state={projects.state} error={projects.error} emptyLabel={tr("No videos yet.")} onRetry={projects.reload}>
        <Rows>
          {rowsOf<Project>(projects.data).map((p) => (
            <Row key={p.id}>
              <div>
                <Link className="font-medium hover:underline" href={`/w/${orgSlug}/studio/${p.id}`}>
                  {p.title}
                </Link>
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("{n} recording(s). {platforms}. Updated {when}.", {
                    n: p.source_assets.length,
                    platforms: p.target_platforms.map((x) => PLATFORM_LABEL[x] ?? x).join(", ") || tr("No platform yet"),
                    when: when(p.updated_at),
                  })}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {p.template ? <Badge>{tr("Template")}</Badge> : null}
                <Badge>{projectStatus(tr, p.status)}</Badge>
                <Button variant="outline" asChild>
                  <Link href={`/w/${orgSlug}/studio/${p.id}`}>{tr("Open")}</Link>
                </Button>
              </div>
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </>
  );
}

function Posts({ orgId }: { orgId: string | null }) {
  const tr = useTr();
  const jobs = useOrgData<PublishJob[]>(orgId, "/publish-jobs", { list: true });
  const rows = rowsOf<PublishJob>(jobs.data);
  const groups: [string, PublishJob[], string][] = [
    [tr("Waiting for approval"), rows.filter((j) => j.status === "awaiting_approval"), tr("Nothing is waiting for approval.")],
    [tr("Scheduled"), rows.filter((j) => ["approved", "scheduled", "publishing"].includes(j.status)), tr("Nothing scheduled.")],
    [tr("Published"), rows.filter((j) => j.status === "published"), tr("Nothing published yet.")],
    [tr("Failed or cancelled"), rows.filter((j) => j.status === "failed" || j.status === "cancelled"), tr("None.")],
  ];
  return (
    <ScreenBody state={jobs.state} error={jobs.error} emptyLabel={tr("No posts yet. Send a render for approval from its project.")} onRetry={jobs.reload}>
      {groups.map(([title, items, empty]) => (
        <Section key={title} title={title}>
          <PublishJobs orgId={orgId} jobs={items} onChange={jobs.reload} emptyLabel={empty} />
        </Section>
      ))}
    </ScreenBody>
  );
}
