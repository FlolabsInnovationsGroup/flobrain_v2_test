"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { flag } from "./access";
import { useAccess } from "./AccessContext";
import { api } from "./api";
import { DEFAULT_LAYOUT, effectiveLayout as layoutFor, type CockpitState, type Layout } from "./layoutRules";

export type { CockpitMode, CockpitState, Layout } from "./layoutRules";
export { DEFAULT_LAYOUT, pollEvery, roomTabHref } from "./layoutRules";

type Ctx = { cockpit: CockpitState; save: (next: Partial<CockpitState>) => Promise<void> };
const LayoutCtx = createContext<Ctx>({
  cockpit: { mode: "default", layout: DEFAULT_LAYOUT, low_bandwidth: false },
  save: async () => undefined,
});

/** Kept for existing callers: the layout without the org's ``cockpit`` flag (use ``useLayout`` in new code). */
export function effectiveLayout(state: CockpitState, cockpitEnabled = true): Layout {
  return layoutFor(state, cockpitEnabled);
}

export function LayoutProvider({ children }: { children: React.ReactNode }) {
  const [cockpit, setCockpit] = useState<CockpitState>({ mode: "default", layout: DEFAULT_LAYOUT, low_bandwidth: false });

  useEffect(() => {
    let cancelled = false;
    api
      .get<CockpitState>("/me/cockpit-layout")
      .then((value) => !cancelled && setCockpit(value))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const save = useCallback(
    async (next: Partial<CockpitState>) => {
      const merged = { ...cockpit, ...next };
      setCockpit(merged);
      setCockpit(await api.put<CockpitState>("/me/cockpit-layout", merged));
    },
    [cockpit],
  );

  return <LayoutCtx.Provider value={{ cockpit, save }}>{children}</LayoutCtx.Provider>;
}

export function useCockpit() {
  return useContext(LayoutCtx);
}

/** The layout as the shell should draw it: the saved choices, the org's ``cockpit`` flag, low bandwidth. */
export function useLayout() {
  const { cockpit, save } = useContext(LayoutCtx);
  const { access } = useAccess();
  const enabled = flag(access, "cockpit");
  return { cockpit, save, enabled, layout: layoutFor(cockpit, enabled), lowBandwidth: cockpit.low_bandwidth };
}

/** True when the person asked for low-bandwidth mode: no images or video, slower polling. */
export function useLowBandwidth(): boolean {
  return useContext(LayoutCtx).cockpit.low_bandwidth;
}
