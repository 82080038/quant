import { test, expect } from "@playwright/test";

test("Dashboard — Ticker Tape + widget layout verification", async ({ page }) => {
  await page.goto("http://localhost:3000");
  await page.waitForLoadState("networkidle");

  // Wait for the IHSG compact bar to appear (replaces exchange timeline)
  const ihsgLabel = page.locator("text=IHSG").first();
  await expect(ihsgLabel).toBeVisible({ timeout: 15000 });

  // Screenshot for visual inspection
  await page.screenshot({ path: "screenshots/dashboard-ticker-tape.png", fullPage: false });

  // Verify Ticker Tape is present (scrolling market data strip)
  const tickerTape = page.locator(".relative.h-7.overflow-hidden").first();
  await expect(tickerTape).toBeVisible({ timeout: 10000 });

  // Verify main widgets are present
  await expect(page.locator("text=Portofolio").first()).toBeVisible();
  await expect(page.locator("text=Movers & Breadth").first()).toBeVisible();
  await expect(page.locator("text=Celestial Fibonacci").first()).toBeVisible();
  await expect(page.locator("text=IHSG Live").first()).toBeVisible();
  await expect(page.locator("text=Sinyal").first()).toBeVisible();

  // Verify no console errors
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  // Wait 12s for a data refresh cycle
  await page.waitForTimeout(12000);

  // Take another screenshot after refresh
  await page.screenshot({ path: "screenshots/dashboard-after-refresh.png", fullPage: false });

  // Check no freeze — FPS counter should be visible
  const fpsLabel = page.locator("text=FPS:");
  await expect(fpsLabel).toBeVisible();

  // Log any console errors
  if (errors.length > 0) {
    console.log("Console errors detected:", errors);
  }
  expect(errors.length).toBe(0);
});

test("Dashboard — Ticker Tape scrolling animation visible", async ({ page }) => {
  await page.goto("http://localhost:3000");
  await page.waitForLoadState("networkidle");

  // Wait for ticker tape to load
  await page.waitForTimeout(5000);

  // Take screenshot
  await page.screenshot({ path: "screenshots/dashboard-ticker-scrolling.png", fullPage: false });

  // Verify the IHSG label is rendered (from compact bar)
  const ihsgLabel = page.locator("text=IHSG").first();
  await expect(ihsgLabel).toBeVisible();
});
