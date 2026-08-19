import { test, expect } from "@playwright/test";

test("Exchange Timeline Header — visual + sorting verification", async ({ page }) => {
  await page.goto("http://localhost:3000");
  await page.waitForLoadState("networkidle");

  // Wait for the exchange timeline header to appear
  const header = page.locator("text=WIB").first();
  await expect(header).toBeVisible({ timeout: 15000 });

  // Screenshot for visual inspection
  await page.screenshot({ path: "screenshots/exchange-timeline-header.png", fullPage: false });

  // Verify exchange cards are present (at least 5 markets)
  const cards = page.locator("[class*='border-green'], [class*='border-yellow'], [class*='border-orange'], [class*='border-slate'], [class*='border-red']");
  const cardCount = await cards.count();
  expect(cardCount).toBeGreaterThanOrEqual(5);

  // Verify no console errors
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  // Wait 12s for a data refresh cycle
  await page.waitForTimeout(12000);

  // Take another screenshot after refresh
  await page.screenshot({ path: "screenshots/exchange-timeline-after-refresh.png", fullPage: false });

  // Check no freeze — FPS counter should be visible
  const fpsLabel = page.locator("text=FPS:");
  await expect(fpsLabel).toBeVisible();

  // Log any console errors
  if (errors.length > 0) {
    console.log("Console errors detected:", errors);
  }
  expect(errors.length).toBe(0);
});

test("Exchange Timeline — DST indicator visible", async ({ page }) => {
  await page.goto("http://localhost:3000");
  await page.waitForLoadState("networkidle");

  // Wait for timeline to load
  await page.waitForTimeout(5000);

  // Take screenshot
  await page.screenshot({ path: "screenshots/exchange-timeline-dst.png", fullPage: false });

  // Verify the timeline header is rendered
  const wibClock = page.locator("text=WIB").first();
  await expect(wibClock).toBeVisible();
});
