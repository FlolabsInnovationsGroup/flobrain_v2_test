"use client";

import { useEffect } from "react";

import { pollEvery, useLowBandwidth } from "@/lib/v2/LayoutContext";
import { ROOM_POLL_MS, shouldPoll } from "@/lib/v2/screens/chat";

export function useRoomMessages(load: () => void, enabled: boolean, hidden = false) {
  const lowBandwidth = useLowBandwidth();
  useEffect(() => {
    if (!shouldPoll(enabled, hidden)) return;
    const timer = window.setInterval(load, pollEvery(ROOM_POLL_MS, lowBandwidth));
    return () => window.clearInterval(timer);
  }, [load, enabled, hidden, lowBandwidth]);
}
