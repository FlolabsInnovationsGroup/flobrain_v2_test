// Zoom's web client as a guest (https://app.zoom.us/wc/join/<id>). Some meetings require signed-in
// users; then joining fails with "signin_required" and the host must allow guests.
import { clickFirst, fillFirst, sendChat, visible, waitForAdmission } from "./common.js";

const IN_CALL = ['button[aria-label*="Leave" i]', '.footer__leave-btn', 'button:has-text("Leave")'];
const DENIED = ["text=/This meeting has been ended by host/i", "text=/You have been removed/i", "text=/only authenticated users/i", "text=/Sign in to join/i"];
const ENDED = ["text=/This meeting has been ended/i", "text=/You have been removed/i", "text=/The meeting has ended/i"];

export function webClientUrl(url) {
  const m = url.match(/zoom\.us\/j\/(\d{9,12})(?:\?pwd=([A-Za-z0-9._-]+))?/);
  if (!m) return url;
  return `https://app.zoom.us/wc/join/${m[1]}${m[2] ? `?pwd=${m[2]}` : ""}`;
}

export const zoom = {
  name: "zoom",
  async join(page, session, timeoutMs) {
    await page.goto(webClientUrl(session.meeting_url), { waitUntil: "domcontentloaded" });
    await clickFirst(page, ['button:has-text("Accept Cookies")', 'button:has-text("I Agree")'], { timeout: 4000 });
    const named = await fillFirst(page, ['#input-for-name', 'input[placeholder*="name" i]'], session.bot_name, { timeout: 30000 });
    if (!named) return (await visible(page, ["text=/Sign in/i"])) ? "signin_required" : "no_join_button";
    await clickFirst(page, ['button[aria-label*="mute" i][aria-label*="audio" i]', 'button:has-text("Mute")'], { timeout: 2000 });
    await clickFirst(page, ['button[aria-label*="stop video" i]', 'button:has-text("Stop Video")'], { timeout: 2000 });
    const asked = await clickFirst(page, ['button.preview-join-button', 'button:has-text("Join")']);
    if (!asked) return "no_join_button";
    await clickFirst(page, ['button:has-text("Join Audio by Computer")', 'button:has-text("Join with Computer Audio")'], { timeout: 20000 });
    return waitForAdmission(page, IN_CALL, DENIED, timeoutMs);
  },
  announce: (page, text) =>
    sendChat(page, ['button[aria-label*="chat" i]', 'button:has-text("Chat")'], ['div[contenteditable="true"]', 'textarea[placeholder*="message" i]'], text),
  async participants(page) {
    const text = await page.locator('.footer-button__number-counter >> nth=0').innerText().catch(() => "");
    const n = Number((text || "").match(/(\d+)/)?.[1]);
    return Number.isFinite(n) && n > 0 ? n : null;
  },
  ended: (page) => visible(page, ENDED),
  leave: (page) => clickFirst(page, IN_CALL, { timeout: 3000 }),
};
