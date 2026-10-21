// Microsoft Teams in the browser as a guest: "Continue on this browser", a name, join, wait in the lobby.
import { clickFirst, fillFirst, sendChat, visible, waitForAdmission } from "./common.js";

const IN_CALL = ['button[aria-label*="Leave" i]', '#hangup-button', 'button[data-tid="hangup-main-btn"]'];
const DENIED = ["text=/Sorry, but you were denied access/i", "text=/You've been removed/i"];
const ENDED = ["text=/You left the meeting/i", "text=/The meeting has ended/i", "text=/You've been removed/i", "text=/Rejoin/i"];

export const teams = {
  name: "teams",
  async join(page, session, timeoutMs) {
    await page.goto(session.meeting_url, { waitUntil: "domcontentloaded" });
    await clickFirst(page, ['button:has-text("Continue on this browser")', 'a:has-text("Continue on this browser")', 'button:has-text("Join on the web instead")'], { timeout: 20000 });
    await fillFirst(page, ['input[data-tid="prejoin-display-name-input"]', 'input[placeholder*="name" i]'], session.bot_name, { timeout: 30000 });
    await clickFirst(page, ['[data-tid="toggle-video"][aria-checked="true"]', '[title*="Turn camera off" i]'], { timeout: 2000 });
    await clickFirst(page, ['[data-tid="toggle-mute"][aria-checked="true"]', '[title*="Mute" i]'], { timeout: 2000 });
    const asked = await clickFirst(page, ['button[data-tid="prejoin-join-button"]', 'button:has-text("Join now")']);
    if (!asked) return "no_join_button";
    return waitForAdmission(page, IN_CALL, DENIED, timeoutMs);
  },
  announce: (page, text) =>
    sendChat(page, ['button[aria-label*="Chat" i]', '#chat-button'], ['div[role="textbox"][contenteditable="true"]', '[data-tid="ckeditor"] [contenteditable="true"]'], text),
  async participants(page) {
    const text = await page.locator('[data-tid="roster-button"] >> nth=0').innerText().catch(() => "");
    const n = Number((text || "").match(/(\d+)/)?.[1]);
    return Number.isFinite(n) && n > 0 ? n : null;
  },
  ended: (page) => visible(page, ENDED),
  leave: (page) => clickFirst(page, IN_CALL, { timeout: 3000 }),
};
