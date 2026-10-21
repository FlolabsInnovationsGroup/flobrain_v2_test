"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, apiError, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

import { AssetsPanel } from "./AssetsPanel";
import { ClipsPanel } from "./ClipsPanel";
import { BrandPanel, CaptionsPanel, FormatPanel, SegmentsPanel } from "./EditPanels";
import { projectStatus } from "./labels";
import { clock, keptSeconds, mediaUrl, PRESET_FOR, type Aspect, type Asset, type Clip, type ConsentProblem, type Edl, type Kit, type Op, type Project, type Word } from "./model";
import { ConsentProblems } from "./PublishJobs";
import { PublishPanel } from "./PublishPanel";
import { RenderQueue } from "./RenderQueue";
import { saveEdl } from "./studioApi";
import { TranscriptEditor } from "./TranscriptEditor";
import { VoiceoverPanel } from "./VoiceoverPanel";

const TABS = ["clips", "edit", "captions", "format", "brand", "voice", "publish"] as const;
type Tab = (typeof TABS)[number];

/** One project: recordings on the left, preview and transcript in the middle, tools on the right, renders below. */
export function ProjectEditor({ orgSlug, projectId }: { orgSlug: string; projectId: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const demo = !!access?.org.demo;
  const project = useOrgData<Project>(orgId, `/content/projects/${projectId}`);
  const library = useOrgData<Asset[]>(orgId, "/content/assets", { list: true });
  const edl = useOrgData<Edl>(orgId, `/content/projects/${projectId}/edl`);
  const clips = useOrgData<Clip[]>(orgId, `/content/projects/${projectId}/suggest-clips`, { list: true });
  const kits = useOrgData<Kit[]>(orgId, "/content/brand-kits", { list: true });
  const [renderKey, setRenderKey] = useState(0);
  const [consentKey, setConsentKey] = useState(0);
  const consent = useOrgData<{ ok: boolean; problems: ConsentProblem[] }>(orgId, `/content/projects/${projectId}/consent?k=${consentKey}`);
  const [picked, setPicked] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("clips");
  const [busy, setBusy] = useState(false);
  const [time, setTime] = useState(0);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const video = useRef<HTMLVideoElement & HTMLAudioElement>(null);

  const p = project.data;
  const selected = picked && p?.source_assets.includes(picked) ? picked : (p?.source_assets[0] ?? null);
  const detail = useOrgData<Asset>(orgId, selected ? `/content/assets/${selected}` : null);
  const transcript = useOrgData<{ status: string; words: Word[] }>(orgId, selected ? `/content/assets/${selected}/transcript` : null);
  const libraryRows = rowsOf<Asset>(library.data);
  const asset = libraryRows.find((a) => a.id === selected) ?? null;
  const words = transcript.data?.words ?? [];
  const ops: Op[] = edl.data?.operations ?? [];
  const version = edl.data?.version ?? 0;
  const kit = rowsOf<Kit>(kits.data).find((k) => k.id === p?.brand_kit) ?? null;
  const running = asset?.transcript_status === "running";
  const { setData: setLibrary } = library;
  const { setData: setTranscript } = transcript;

  // While a transcription runs, check every few seconds without flashing the page.
  useEffect(() => {
    if (!running || !orgId || !selected) return;
    const timer = window.setInterval(() => {
      api.get<Asset[]>(`/orgs/${orgId}/content/assets`).then(setLibrary).catch(() => undefined);
      api.get<{ status: string; words: Word[] }>(`/orgs/${orgId}/content/assets/${selected}/transcript`).then(setTranscript).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, orgId, selected, setLibrary, setTranscript]);

  function seek(t: number) {
    if (video.current) {
      video.current.currentTime = t;
      video.current.play().catch(() => undefined);
    }
  }

  async function change(next: Op[], note: string) {
    if (!orgId) return;
    setBusy(true);
    setMessage(null);
    try {
      edl.setData(await saveEdl(orgId, projectId, next, version, note));
    } catch (err) {
      const e = apiError(err);
      setMessage({ kind: "error", text: e.status === 409 ? tr("Someone else changed this edit. The latest version is loaded; try again.") : errorText(err) });
      edl.reload();
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    setBusy(true);
    setMessage(null);
    try {
      edl.setData(await api.post<Edl>(`/orgs/${orgId}/content/projects/${projectId}/edl/revert`, { version: version - 1 }));
      setMessage({ kind: "ok", text: tr("Back to the previous version.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function patch(fields: Partial<Project>) {
    setMessage(null);
    try {
      project.setData(await api.patch<Project>(`/orgs/${orgId}/content/projects/${projectId}`, fields));
      setConsentKey((n) => n + 1);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function render(aspects: Aspect[]) {
    setBusy(true);
    setMessage(null);
    try {
      for (const a of aspects) await api.post(`/orgs/${orgId}/content/projects/${projectId}/render`, { preset: PRESET_FOR[a] });
      setMessage({
        kind: "ok",
        text: demo
          ? tr("Render queued. In the demo, a sample video is ready in a few seconds.")
          : tr("Render queued. A GPU worker picks it up; progress shows below."),
      });
      setRenderKey((n) => n + 1);
    } catch (err) {
      const e = apiError(err);
      setMessage({
        kind: "error",
        text: e.code === "quota_exceeded" ? tr("Your org used its renders for this month ({details}).", { details: e.details }) : errorText(err),
      });
    } finally {
      setBusy(false);
    }
  }

  const tabLabel: Record<Tab, string> = {
    clips: tr("Clips"),
    edit: tr("Cuts"),
    captions: tr("Captions"),
    format: tr("Format"),
    brand: tr("Brand"),
    voice: tr("Voice"),
    publish: tr("Publish"),
  };

  return (
    <ScreenBody state={project.state} error={project.error} onRetry={project.reload}>
      {p ? (
        <div>
          <PageHeader
            title={p.title}
            intro={tr("Edit the transcript to edit the video. The source file never changes; every edit is a version you can undo.")}
            action={
              <div className="flex items-center gap-2">
                {demo ? <Badge tone="waiting">{tr("Demo")}</Badge> : null}
                <Badge>{projectStatus(tr, p.status)}</Badge>
                <Button variant="ghost" asChild>
                  <Link href={`/w/${orgSlug}/studio`}>{tr("All projects")}</Link>
                </Button>
              </div>
            }
          />
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
          {consent.data && !consent.data.ok ? <ConsentProblems problems={consent.data.problems} /> : null}

          {/* Wide screens: recordings | preview and transcript | tools. Narrower: recordings move under the preview. */}
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[260px_minmax(0,1fr)_380px]">
            <aside className="lg:col-start-1 lg:row-start-2 2xl:row-start-1">
              <AssetsPanel
                orgId={orgId}
                project={p}
                library={libraryRows}
                selected={selected}
                onSelect={setPicked}
                onProjectChange={(value) => {
                  project.setData(value);
                  setConsentKey((n) => n + 1);
                }}
                onLibraryChange={library.reload}
                onConsentChange={() => setConsentKey((n) => n + 1)}
              />
            </aside>

            <section aria-label={tr("Preview and transcript")} className="min-w-0 lg:col-start-1 lg:row-start-1 2xl:col-start-2">
              {selected && detail.data?.url ? (
                asset?.kind === "audio" ? (
                  <audio ref={video} className="mb-4 w-full" src={mediaUrl(detail.data.url)} controls onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} />
                ) : (
                  <video
                    ref={video}
                    className="mb-2 aspect-video w-full rounded-xl bg-black"
                    src={mediaUrl(detail.data.url)}
                    controls
                    playsInline
                    preload="metadata"
                    onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                  />
                )
              ) : (
                <div className="mb-4 flex aspect-video items-center justify-center rounded-xl bg-[color:var(--fb-v2-surface)] text-sm text-[color:var(--fb-v2-text-muted)]">
                  {selected ? tr("Loading the preview") : tr("No recording yet")}
                </div>
              )}
              {asset?.duration_seconds ? (
                <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("Edited length {kept} of {total}", { kept: clock(keptSeconds(ops, asset.id, asset.duration_seconds)), total: clock(asset.duration_seconds) })}
                  {demo ? ` · ${tr("Demo recording with sample speech")}` : ""}
                </p>
              ) : null}
              {selected && words.length ? (
                <TranscriptEditor
                  words={words}
                  ops={ops}
                  asset={selected}
                  clips={rowsOf<Clip>(clips.data)}
                  currentTime={time}
                  busy={busy}
                  onSeek={seek}
                  onChange={change}
                />
              ) : selected ? (
                <Notice>{running ? tr("Transcribing. The words appear here when it finishes.") : tr("No transcript yet. Press Transcribe on the recording to edit by text.")}</Notice>
              ) : null}
            </section>

            <aside className="lg:col-start-2 lg:row-span-2 lg:row-start-1 2xl:col-start-3 2xl:row-span-1">
              <div role="tablist" aria-label={tr("Tools")} className="mb-4 flex flex-wrap gap-1 border-b border-[color:var(--fb-v2-border)]">
                {TABS.map((name) => (
                  <button
                    key={name}
                    role="tab"
                    aria-selected={tab === name}
                    onClick={() => setTab(name)}
                    className={cn(
                      "-mb-px border-b-2 px-2 py-2 text-sm",
                      tab === name ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]",
                    )}
                  >
                    {tabLabel[name]}
                  </button>
                ))}
              </div>
              <div role="tabpanel">
                {tab === "clips" ? (
                  <ClipsPanel
                    orgId={orgId}
                    projectId={projectId}
                    assetId={selected}
                    hasTranscript={words.length > 0}
                    clips={rowsOf<Clip>(clips.data)}
                    demo={demo}
                    onClips={(value) => clips.setData(value)}
                    onEdl={(value) => edl.setData(value)}
                    onSeek={seek}
                  />
                ) : null}
                {tab === "edit" ? <SegmentsPanel assetId={selected} ops={ops} version={version} busy={busy} onChange={change} onUndo={undo} onSeek={seek} /> : null}
                {tab === "captions" ? (
                  <CaptionsPanel orgId={orgId} projectId={projectId} assetId={selected} ops={ops} kit={kit} hasTranscript={words.length > 0} busy={busy} onChange={change} />
                ) : null}
                {tab === "format" ? (
                  <FormatPanel project={p} asset={asset} ops={ops} busy={busy} onChange={change} onPlatforms={(target_platforms) => patch({ target_platforms })} onRender={render} />
                ) : null}
                {tab === "brand" ? (
                  <BrandPanel kits={rowsOf<Kit>(kits.data)} project={p} ops={ops} busy={busy} onKit={(brand_kit) => patch({ brand_kit })} onChange={change} />
                ) : null}
                {tab === "voice" ? (
                  <VoiceoverPanel
                    orgId={orgId}
                    projectId={projectId}
                    onAdded={() => {
                      library.reload();
                      project.reload();
                    }}
                  />
                ) : null}
                {tab === "publish" ? <PublishPanel orgId={orgId} project={p} orgSlug={orgSlug} /> : null}
              </div>
            </aside>
          </div>

          <section className="mt-8" aria-label={tr("Render queue")}>
            <h2 className="mb-3 text-lg font-semibold">{tr("Render queue")}</h2>
            <RenderQueue orgId={orgId} path={`/content/projects/${projectId}/render`} refreshKey={renderKey} />
          </section>
        </div>
      ) : null}
    </ScreenBody>
  );
}
