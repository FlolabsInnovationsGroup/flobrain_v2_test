"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { errorText } from "@/lib/v2/api";
import { cn } from "@/lib/utils";

import { aspectHint } from "./labels";
import {
  BEST_ASPECT,
  PLATFORM_LABEL,
  PLATFORMS,
  clock,
  cutsOf,
  findOp,
  keepsOf,
  moveKeep,
  removeOp,
  setSingle,
  type Aspect,
  type Asset,
  type Kit,
  type Op,
  type Project,
} from "./model";
import { downloadCaptions } from "./studioApi";

type Change = (ops: Op[], note: string) => void;

const LANGUAGES: [string, string][] = [
  ["en", "English"],
  ["ar", "العربية"],
  ["fr", "Français"],
  ["tr", "Türkçe"],
  ["pt", "Português"],
  ["es", "Español"],
  ["de", "Deutsch"],
];

export function CaptionsPanel({
  orgId,
  projectId,
  assetId,
  ops,
  kit,
  hasTranscript,
  busy,
  onChange,
}: {
  orgId: string | null;
  projectId: string;
  assetId: string | null;
  ops: Op[];
  kit: Kit | null;
  hasTranscript: boolean;
  busy: boolean;
  onChange: Change;
}) {
  const tr = useTr();
  const captions = findOp(ops, "captions");
  const [error, setError] = useState<string | null>(null);
  const style = kit?.caption_style ?? {};
  const set = (language: string, burnIn: boolean) =>
    onChange(setSingle(ops, "captions", { op: "captions", language, burn_in: burnIn }), `captions ${language}`);

  return (
    <div>
      <label className="mb-3 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={!!captions}
          disabled={busy}
          onChange={(e) => (e.target.checked ? set("en", true) : onChange(setSingle(ops, "captions", null), "captions off"))}
        />
        <span className="font-medium">{tr("Captions on")}</span>
      </label>
      {captions ? (
        <>
          <label className="mb-3 block text-sm">
            <span className="mb-1 block font-medium">{tr("Caption language")}</span>
            <select className="v2-input" value={captions.language} disabled={busy} onChange={(e) => set(e.target.value, captions.burn_in)}>
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[color:var(--fb-v2-text-muted)]">
              {tr("Pick the language spoken in the recording. Captions come from its transcript; translating captions isn't available yet.")}
            </span>
          </label>
          <fieldset className="mb-3 text-sm">
            <legend className="mb-1 font-medium">{tr("How captions are delivered")}</legend>
            <label className="me-4 inline-flex items-center gap-1">
              <input type="radio" name="burn" checked={captions.burn_in} disabled={busy} onChange={() => set(captions.language, true)} />
              {tr("Burned into the video")}
            </label>
            <label className="inline-flex items-center gap-1">
              <input type="radio" name="burn" checked={!captions.burn_in} disabled={busy} onChange={() => set(captions.language, false)} />
              {tr("Separate file only")}
            </label>
          </fieldset>
          <p className="mb-1 text-sm font-medium">{tr("Style from the brand kit")}</p>
          {kit ? (
            <div className="mb-3 flex h-24 items-end justify-center rounded-lg bg-black/80 p-3" aria-label={tr("Caption style preview")}>
              <span
                className="rounded px-2 py-1 text-base font-semibold"
                style={{
                  color: style.color || "#ffffff",
                  background: style.background || "rgba(0,0,0,0.6)",
                  fontFamily: style.font || kit.fonts.heading || undefined,
                }}
                dir="auto"
              >
                {captions.language === "ar" ? "نطلق التطبيق الشهر القادم" : tr("We launch at the end of next month")}
              </span>
            </div>
          ) : (
            <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No brand kit on this project. Captions use the default style.")}</p>
          )}
        </>
      ) : null}
      {hasTranscript ? (
        <div className="flex flex-wrap gap-2">
          {(["srt", "vtt"] as const).map((fmt) => (
            <Button
              key={fmt}
              variant="outline"
              onClick={() => {
                if (!orgId) return;
                setError(null);
                downloadCaptions(orgId, projectId, fmt, assetId ?? undefined).catch((err) => setError(errorText(err)));
              }}
            >
              {fmt === "srt" ? tr("Download SRT") : tr("Download VTT")}
            </Button>
          ))}
        </div>
      ) : (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Captions need a transcript.")}</p>
      )}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </div>
  );
}

const ASPECTS: Aspect[] = ["9:16", "1:1", "16:9"];

export function FormatPanel({
  project,
  asset,
  ops,
  busy,
  onChange,
  onPlatforms,
  onRender,
}: {
  project: Project;
  asset: Asset | null;
  ops: Op[];
  busy: boolean;
  onChange: Change;
  onPlatforms: (platforms: string[]) => void;
  onRender: (aspects: Aspect[]) => void;
}) {
  const tr = useTr();
  const reframe = findOp(ops, "reframe");
  const aspect: Aspect = reframe?.aspect ?? "16:9";
  const wanted = Array.from(new Set(project.target_platforms.map((p) => BEST_ASPECT[p]?.[0]).filter(Boolean))) as Aspect[];
  const sourceRatio = asset?.width && asset?.height ? asset.width / asset.height : 16 / 9;
  const [w, h] = aspect.split(":").map(Number);
  const cropWidth = Math.min(1, w / h / sourceRatio);
  const crop = reframe?.crop;

  function setAspect(next: Aspect) {
    onChange(setSingle(ops, "reframe", { op: "reframe", aspect: next, mode: "auto" }), `format ${next}`);
  }

  return (
    <div>
      <fieldset className="mb-4 text-sm">
        <legend className="mb-1 font-medium">{tr("Platforms")}</legend>
        {PLATFORMS.map((p) => (
          <label key={p} className="me-3 inline-flex items-center gap-1">
            <input
              type="checkbox"
              checked={project.target_platforms.includes(p)}
              disabled={busy}
              onChange={(e) => onPlatforms(e.target.checked ? [...project.target_platforms, p] : project.target_platforms.filter((x) => x !== p))}
            />
            {PLATFORM_LABEL[p]}
          </label>
        ))}
      </fieldset>
      <p className="mb-2 text-sm font-medium">{tr("Aspect ratio")}</p>
      <div className="mb-3 grid grid-cols-3 gap-2" role="radiogroup" aria-label={tr("Aspect ratio")}>
        {ASPECTS.map((a) => {
          const [aw, ah] = a.split(":").map(Number);
          return (
            <button
              key={a}
              type="button"
              role="radio"
              aria-checked={aspect === a}
              disabled={busy}
              onClick={() => setAspect(a)}
              className={cn(
                "flex flex-col items-center gap-2 rounded-lg p-3 text-sm ring-1 ring-inset",
                aspect === a ? "ring-2 ring-[color:var(--fb-v2-accent)]" : "ring-[color:var(--fb-v2-border)]",
              )}
            >
              <span className="block rounded-sm bg-[color:var(--fb-v2-border)]" style={{ width: aw > ah ? 48 : (48 * aw) / ah, height: ah > aw ? 48 : (48 * ah) / aw }} aria-hidden />
              <span className="font-medium">{a}</span>
              {wanted.includes(a) ? <Badge tone="accent">{tr("Your platforms")}</Badge> : null}
            </button>
          );
        })}
      </div>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{aspectHint(tr, aspect)}</p>
      {aspect !== "16:9" || sourceRatio < 1.7 ? (
        <fieldset className="mb-4 text-sm">
          <legend className="mb-1 font-medium">{tr("Reframe")}</legend>
          <label className="me-4 inline-flex items-center gap-1">
            <input type="radio" name="reframe" checked={!crop} disabled={busy} onChange={() => setAspect(aspect)} />
            {tr("Follow the speaker automatically")}
          </label>
          <label className="inline-flex items-center gap-1">
            <input
              type="radio"
              name="reframe"
              checked={!!crop}
              disabled={busy}
              onChange={() =>
                onChange(
                  setSingle(ops, "reframe", { op: "reframe", aspect, mode: "manual", crop: { x: round((1 - cropWidth) / 2), y: 0, w: round(cropWidth), h: 1 } }),
                  `manual crop ${aspect}`,
                )
              }
            />
            {tr("Fixed crop")}
          </label>
          {crop ? (
            <label className="mt-2 block">
              <span className="mb-1 block">{tr("Crop position, left to right")}</span>
              <input
                type="range"
                min={0}
                max={Math.max(0, 1 - crop.w)}
                step={0.01}
                value={crop.x}
                disabled={busy}
                className="w-full"
                onChange={(e) =>
                  onChange(setSingle(ops, "reframe", { op: "reframe", aspect, mode: "manual", crop: { ...crop, x: round(Number(e.target.value)) } }), "move crop")
                }
              />
              <span className="relative mt-2 block h-16 overflow-hidden rounded bg-[color:var(--fb-v2-border)]" style={{ aspectRatio: String(sourceRatio) }} aria-hidden>
                <span className="absolute inset-y-0 rounded ring-2 ring-[color:var(--fb-v2-accent)]" style={{ left: `${crop.x * 100}%`, width: `${crop.w * 100}%` }} />
              </span>
            </label>
          ) : null}
        </fieldset>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => onRender([aspect])} disabled={busy}>
          {tr("Render {aspect}", { aspect })}
        </Button>
        {wanted.length > 1 || (wanted.length === 1 && wanted[0] !== aspect) ? (
          <Button variant="outline" onClick={() => onRender(wanted)} disabled={busy}>
            {tr("Render for all platforms ({list})", { list: wanted.join(", ") })}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function round(n: number) {
  return Math.round(n * 1000) / 1000;
}

export function BrandPanel({
  kits,
  project,
  ops,
  busy,
  onKit,
  onChange,
}: {
  kits: Kit[];
  project: Project;
  ops: Op[];
  busy: boolean;
  onKit: (id: string | null) => void;
  onChange: Change;
}) {
  const tr = useTr();
  const kit = kits.find((k) => k.id === project.brand_kit) ?? null;
  return (
    <div>
      <label className="mb-3 block text-sm">
        <span className="mb-1 block font-medium">{tr("Brand kit")}</span>
        <select className="v2-input" value={project.brand_kit ?? ""} disabled={busy} onChange={(e) => onKit(e.target.value || null)}>
          <option value="">{tr("No brand kit")}</option>
          {kits.map((k) => (
            <option key={k.id} value={k.id}>
              {k.name}
            </option>
          ))}
        </select>
      </label>
      {kit ? (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-2">
            {Object.entries(kit.colors).map(([name, hex]) => (
              <span key={name} className="flex items-center gap-1 text-xs">
                <span className="inline-block h-5 w-5 rounded" style={{ background: hex }} aria-hidden />
                {name} {hex}
              </span>
            ))}
          </div>
          {Object.keys(kit.fonts).length ? <p>{tr("Fonts: {fonts}", { fonts: Object.values(kit.fonts).join(", ") })}</p> : null}
          {kit.logos.length ? <p>{tr("{n} logo(s). The watermark follows the kit.", { n: kit.logos.length })}</p> : null}
          {(["intro", "outro"] as const).map((part) => {
            const has = part === "intro" ? kit.intro_asset : kit.outro_asset;
            const on = !!findOp(ops, part);
            return has ? (
              <label key={part} className="flex items-center gap-2">
                <input type="checkbox" checked={on} disabled={busy} onChange={(e) => onChange(setSingle(ops, part, e.target.checked ? { op: part } : null), `${part} ${e.target.checked ? "on" : "off"}`)} />
                {part === "intro" ? tr("Add the brand intro") : tr("Add the brand outro")}
              </label>
            ) : null;
          })}
          {!kit.intro_asset && !kit.outro_asset ? <p className="text-[color:var(--fb-v2-text-muted)]">{tr("This kit has no intro or outro video.")}</p> : null}
        </div>
      ) : (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Pick a brand kit for colours, fonts, caption style and logo.")}</p>
      )}
    </div>
  );
}

/** Segments in playing order (reorder, remove) and the list of cuts (restore). */
export function SegmentsPanel({
  assetId,
  ops,
  version,
  busy,
  onChange,
  onUndo,
  onSeek,
}: {
  assetId: string | null;
  ops: Op[];
  version: number;
  busy: boolean;
  onChange: Change;
  onUndo: () => void;
  onSeek: (t: number) => void;
}) {
  const tr = useTr();
  const keeps = keepsOf(ops);
  const cuts = assetId ? cutsOf(ops, assetId).sort((a, b) => a.start - b.start) : [];
  return (
    <div className="space-y-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[color:var(--fb-v2-text-muted)]">{version ? tr("Edit version {v}", { v: version }) : tr("No edits yet")}</span>
        <Button variant="outline" disabled={busy || version < 2} onClick={onUndo}>
          {tr("Undo")}
        </Button>
      </div>
      <div>
        <p className="mb-1 font-medium">{tr("Segments, in playing order")}</p>
        {keeps.length ? (
          <ol className="space-y-1">
            {keeps.map((k, n) => (
              <li key={`${k.asset}-${k.start}-${n}`} className="flex flex-wrap items-center justify-between gap-2 rounded px-2 py-1 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
                <button type="button" className="text-start" onClick={() => onSeek(k.start)}>
                  {n + 1}. {tr("{from} to {to}", { from: clock(k.start), to: clock(k.end) })}
                </button>
                <span className="flex gap-1">
                  <Button variant="ghost" className="px-2 py-1 text-xs" disabled={busy || n === 0} onClick={() => onChange(moveKeep(ops, n, -1), "move segment up")} aria-label={tr("Move up")}>
                    ↑
                  </Button>
                  <Button
                    variant="ghost"
                    className="px-2 py-1 text-xs"
                    disabled={busy || n === keeps.length - 1}
                    onClick={() => onChange(moveKeep(ops, n, 1), "move segment down")}
                    aria-label={tr("Move down")}
                  >
                    ↓
                  </Button>
                  <Button variant="ghost" className="px-2 py-1 text-xs" disabled={busy} onClick={() => onChange(removeOp(ops, k), "remove segment")}>
                    {tr("Remove")}
                  </Button>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[color:var(--fb-v2-text-muted)]">{tr("The whole recording plays. Keep a clip or a selection to make segments.")}</p>
        )}
      </div>
      <div>
        <p className="mb-1 font-medium">{tr("Cuts")}</p>
        {cuts.length ? (
          <ul className="space-y-1">
            {cuts.map((c, n) => (
              <li key={`${c.start}-${n}`} className="flex items-center justify-between gap-2">
                <button type="button" className="text-start" onClick={() => onSeek(Math.max(0, c.start - 1))}>
                  {tr("{from} to {to}", { from: clock(c.start), to: clock(c.end) })}
                  <span className="text-[color:var(--fb-v2-text-muted)]">
                    {" "}
                    · {c.reason === "filler" ? tr("filler") : c.reason === "silence" ? tr("silence") : c.reason === "noise" ? tr("noise") : tr("your cut")}
                    {c.by === "ai" ? ` · ${tr("AI")}` : ""}
                  </span>
                </button>
                <Button variant="ghost" className="px-2 py-1 text-xs" disabled={busy} onClick={() => onChange(removeOp(ops, c), "restore cut")}>
                  {tr("Restore")}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[color:var(--fb-v2-text-muted)]">{tr("Nothing is cut.")}</p>
        )}
      </div>
    </div>
  );
}
