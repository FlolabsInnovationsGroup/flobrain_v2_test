// Helpers shared by the platform adapters. Selectors change over time, so each step tries several.

export async function clickFirst(page, selectors, { timeout = 15000 } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const el = page.locator(selector).first();
      if (await el.isVisible().catch(() => false)) {
        await el.click().catch(() => undefined);
        return selector;
      }
    }
    await page.waitForTimeout(500);
  }
  return null;
}

export async function fillFirst(page, selectors, value, { timeout = 15000 } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const el = page.locator(selector).first();
      if (await el.isVisible().catch(() => false)) {
        await el.fill(value).catch(() => undefined);
        return selector;
      }
    }
    await page.waitForTimeout(500);
  }
  return null;
}

export async function visible(page, selectors) {
  for (const selector of selectors) {
    if (await page.locator(selector).first().isVisible().catch(() => false)) return true;
  }
  return false;
}

/** Wait until one of `success` shows up; returns "joined", "denied" or "timeout". */
export async function waitForAdmission(page, success, denied, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await visible(page, success)) return "joined";
    if (await visible(page, denied)) return "denied";
    await page.waitForTimeout(1000);
  }
  return "timeout";
}

export async function sendChat(page, openSelectors, inputSelectors, text) {
  await clickFirst(page, openSelectors, { timeout: 5000 });
  const input = await fillFirst(page, inputSelectors, text, { timeout: 5000 });
  if (!input) return false;
  await page.locator(input).first().press("Enter").catch(() => undefined);
  // Only count it as said when our words show up in the meeting chat.
  const words = text.slice(0, 40);
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (await page.getByText(words, { exact: false }).first().isVisible().catch(() => false)) return true;
    await page.waitForTimeout(500);
  }
  return false;
}
