import { expect, test } from "@playwright/test";

test("journey 1 skeleton: V2 sign-in is reachable", async ({ page }) => {
  await page.goto("/w/signin");
  await expect(page.getByRole("heading")).toBeVisible();
});
