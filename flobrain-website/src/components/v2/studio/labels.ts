/** Display text for Studio states. Literal tr() calls so every label has an Arabic line. */

import type { PublishJob, Render } from "./model";

type Tr = (text: string, vars?: Record<string, string | number>) => string;
type Tone = "neutral" | "waiting" | "good" | "bad" | "accent";

export function renderStatus(tr: Tr, status: Render["status"]): { text: string; tone: Tone } {
  switch (status) {
    case "queued":
      return { text: tr("render|Queued"), tone: "neutral" };
    case "running":
      return { text: tr("render|Rendering"), tone: "accent" };
    case "succeeded":
      return { text: tr("render|Done"), tone: "good" };
    case "failed":
      return { text: tr("render|Failed"), tone: "bad" };
    default:
      return { text: tr("render|Cancelled"), tone: "neutral" };
  }
}

export function publishStatus(tr: Tr, status: PublishJob["status"]): { text: string; tone: Tone } {
  switch (status) {
    case "awaiting_approval":
      return { text: tr("post|Waiting for approval"), tone: "waiting" };
    case "approved":
      return { text: tr("post|Approved"), tone: "accent" };
    case "scheduled":
      return { text: tr("post|Scheduled"), tone: "accent" };
    case "publishing":
      return { text: tr("post|Publishing"), tone: "accent" };
    case "published":
      return { text: tr("post|Published"), tone: "good" };
    case "failed":
      return { text: tr("post|Failed"), tone: "bad" };
    default:
      return { text: tr("post|Cancelled"), tone: "neutral" };
  }
}

export function projectStatus(tr: Tr, status: string): string {
  switch (status) {
    case "processing":
      return tr("project|Processing");
    case "ready":
      return tr("project|Ready");
    case "failed":
      return tr("project|Failed");
    default:
      return tr("project|Draft");
  }
}

export function scopeLabel(tr: Tr, scope: string): string {
  switch (scope) {
    case "internal":
      return tr("Inside the company");
    case "marketing":
      return tr("Marketing and ads");
    default:
      return tr("Public social posts");
  }
}

/** Why a post was held back, in plain words. */
export function publishError(tr: Tr, code: string): string {
  switch (code) {
    case "consent_missing":
      return tr("Held back: someone in the video has not consented.");
    case "changed_after_approval":
      return tr("Held back: the post changed after approval. Approve it again.");
    case "output_changed":
      return tr("Held back: the video file changed after approval. Approve it again.");
    case "account_not_connected":
      return tr("The social account is no longer connected.");
    case "connector_not_configured":
      return tr("This platform is not set up yet.");
    case "render_not_ready":
      return tr("The video is not ready.");
    default:
      return code ? tr("Publishing failed ({code}).", { code }) : "";
  }
}

export function aspectHint(tr: Tr, aspect: string): string {
  switch (aspect) {
    case "9:16":
      return tr("Vertical. TikTok, Reels, Shorts.");
    case "1:1":
      return tr("Square. LinkedIn and Instagram feeds.");
    default:
      return tr("Wide. YouTube and LinkedIn video.");
  }
}
