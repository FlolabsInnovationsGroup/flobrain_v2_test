/** What the saved cockpit settings mean for the shell (pure, so it can be tested in node). */

export type CockpitMode = "default" | "focus" | "custom";
export type Layout = {
  panels: { rooms: boolean; video: boolean; compact: boolean; right_rail: boolean };
  widgets: string[];
  default_room_tab: string;
  accent: string;
};
export type CockpitState = { mode: CockpitMode; layout: Layout; low_bandwidth: boolean };

export const DEFAULT_LAYOUT: Layout = {
  panels: { rooms: true, video: false, compact: false, right_rail: true },
  widgets: ["impact", "progress", "tasks", "approvals", "buddies"],
  default_room_tab: "chat",
  accent: "",
};

export const ROOM_TABS = ["chat", "ai", "tasks", "docs", "calendar", "recordings", "report", "team"] as const;

/**
 * What each mode shows: Focus hides everything but the page; Custom uses the saved choices.
 * Without the ``cockpit`` flag every org gets Default. Low bandwidth always drops the video panel.
 */
export function effectiveLayout(state: CockpitState, cockpitEnabled = true): Layout {
  let out: Layout;
  if (!cockpitEnabled) out = { ...DEFAULT_LAYOUT };
  else if (state.mode === "focus") out = { ...state.layout, panels: { rooms: false, video: false, compact: true, right_rail: false }, widgets: ["tasks", "approvals"] };
  else if (state.mode === "default") out = { ...DEFAULT_LAYOUT, accent: state.layout.accent };
  else out = state.layout;
  if (state.low_bandwidth) out = { ...out, panels: { ...out.panels, video: false } };
  return out;
}

/** Slower polling on a slow connection: four times the normal interval, at least a minute. */
export function pollEvery(ms: number, lowBandwidth: boolean): number {
  return lowBandwidth ? Math.max(ms * 4, 60000) : ms;
}

/** The page a room opens on, from the saved default tab. Tabs without their own page open the chat. */
export function roomTabHref(orgSlug: string, roomId: string, tab: string): string {
  const base = `/w/${orgSlug}/rooms/${roomId}`;
  switch (tab) {
    case "ai":
      return `${base}/ai`;
    case "docs":
      return `${base}/docs`;
    case "recordings":
      return `${base}/meetings`;
    case "tasks":
      return `/w/${orgSlug}/tasks?room=${roomId}`;
    case "calendar":
      return `/w/${orgSlug}/calendar?room=${roomId}`;
    default:
      return base;
  }
}

/** A link to a room's front page (``/w/x/rooms/<id>``), the only kind the default tab redirects. */
export function roomFromHref(href: string, orgSlug: string): string | null {
  const m = href.match(new RegExp(`^/w/${orgSlug.replace(/[^a-z0-9-]/gi, "")}/rooms/([0-9a-f-]{36})$`, "i"));
  return m ? m[1] : null;
}
