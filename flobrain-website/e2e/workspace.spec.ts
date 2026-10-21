import { expect, test, type Page } from "@playwright/test";

const hasBackend = process.env.E2E_HAS_BACKEND === "1";

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/w/signin");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.waitForFunction(() => {
    const form = document.querySelector("form");
    return !!form && Object.keys(form).some((key) => key.startsWith("__react"));
  });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const posted = page.waitForResponse(
    (res) => res.url().includes("/api/v2/auth/signin") && res.request().method() === "POST",
    { timeout: 20000 },
  );
  await page.getByRole("button", { name: "Continue" }).click();
  const response = await posted;
  expect(response.ok(), `signin failed: ${response.status()}`).toBeTruthy();
}

test.describe("V2 workspace smokes", () => {
  test.skip(!hasBackend, "requires local Django venv, migrate, and seed_v2_demo");

  test("sign in, rooms, tasks, Flo Chronos timer, and permission denial", async ({ page }) => {
    await signIn(page, "member.product@flolabs.local", "demo-member-pass");
    await expect(page).toHaveURL(/\/w\/flolabs/, { timeout: 20000 });
    await expect(page.getByRole("heading", { name: "Cockpit" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Rooms" })).toBeVisible();

    await page.getByRole("link", { name: "Product" }).click();
    await expect(page).toHaveURL(/\/w\/flolabs\/rooms\//);
    await expect(page.getByRole("heading", { name: "Product" })).toBeVisible();
    await page.getByPlaceholder("Write a message").fill("hello from e2e");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("hello from e2e")).toBeVisible();

    await page.goto("/w/flolabs/tasks");
    await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();

    await expect(page.getByRole("button", { name: "Start" })).toBeEnabled();
    await page.getByRole("button", { name: "Start" }).click();
    await expect(page.getByText("Timer running")).toBeVisible();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByText("Timer stopped")).toBeVisible();

    await page.goto("/w/flolabs/mission-control");
    await expect(page.getByText("You do not have access")).toBeVisible();
  });

  test("owner can switch workspace", async ({ page }) => {
    await signIn(page, "owner@flolabs.local", "demo-owner-pass");
    await expect(page).toHaveURL(/\/w\/flolabs/, { timeout: 20000 });
    const workspace = page.getByLabel("Workspace");
    await expect(workspace).toBeVisible();
    await expect(workspace.locator("option[value='acme']")).toHaveCount(1, { timeout: 15000 });
    await workspace.selectOption("acme");
    await expect(page).toHaveURL(/\/w\/acme/);
    await expect(page.getByRole("heading", { name: "Cockpit" })).toBeVisible();
  });
});
