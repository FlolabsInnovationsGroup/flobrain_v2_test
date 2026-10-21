"use client";

import { useEffect } from "react";

import { ROOM_POLL_MS, shouldPoll } from "@/lib/v2/screens/chat";

export function useRoomMessages(load: () => void, enabled: boolean, hidden = false) {
  useEffect(() => {
    if (!shouldPoll(enabled, hidden)) return;
    const timer = window.setInterval(load, ROOM_POLL_MS);
    return () => window.clearInterval(timer);
  }, [load, enabled, hidden]);
}
