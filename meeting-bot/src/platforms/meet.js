// Google Meet as a guest: type a name, ask to join, wait for the host to admit us.
import { clickFirst, fillFirst, sendChat, visible, waitForAdmission } from "./common.js";

const IN_CALL = ['button[aria-label*="Leave call" i]', '[aria-label*="Leave call" i]'];
const DENIED = ["text=/You can't join this video call/i", "text=/Someone in the call denied your request/i", "text=/You've been removed/i"];
const ENDED = ["text=/You left the meeting/i", "text=/The call ended/i", "text=/You've been removed/i", "text=/Rejoin/i"];

export const meet = {
  name: "meet",
  async join(page, session, timeoutMs) {
    await page.goto(session.meeting_url, { waitUntil: "domcontentloaded" });
    await clickFirst(page, ['button:has-text("Continue without microphone and camera")', 'button:has-text("Dismiss")', 'button:has-text("Got it")'], { timeout: 6000 });
    await fillFirst(page, ['input[aria-label="Your name"]', 'input[placeholder="Your name"]', 'input[type="text"]'], session.bot_name);
    await clickFirst(page, ['[aria-label*="Turn off microphone" i]'], { timeout: 2000 });
    await clickFirst(page, ['[aria-label*="Turn off camera" i]'], { timeout: 2000 });
    const asked = await clickFirst(page, ['button:has-text("Ask to join")', 'button:has-text("Join now")', 'span:has-text("Ask to join")']);
    if (!asked) return "no_join_button";
    return waitForAdmission(page, IN_CALL, DENIED, timeoutMs);
  },
  announce: (page, text) =>
    sendChat(page, ['button[aria-label*="Chat with everyone" i]', 'button[aria-label*="chat" i]'], ['textarea[aria-label*="Send a message" i]', "textarea"], text),
  async participants(page) {
    const label = await page.locator('[aria-label*="participant" i] >> nth=0').getAttribute("aria-label").catch(() => "");
    const n = Number((label || "").match(/(\d+)/)?.[1]);
    return Number.isFinite(n) && n > 0 ? n : null;
  },
  ended: (page) => visible(page, ENDED),
  leave: (page) => clickFirst(page, IN_CALL, { timeout: 3000 }),
};
