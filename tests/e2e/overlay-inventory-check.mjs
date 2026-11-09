import { chromium, expect } from "@playwright/test";
import fs from "node:fs";

const { origin, password } = JSON.parse(fs.readFileSync(process.env.COMMONS_ATOMIC_FIXTURE, "utf8"));
const results = process.env.COMMONS_ATOMIC_RESULTS;
const mode = process.env.COMMONS_TEST_INVENTORY_MODE;
const browser = await chromium.launch({ executablePath: process.env.COMMONS_CHROMIUM_BINARY });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const endpoint = origin + "/api/overlay-inventory";
const nav = page.getByRole("navigation");
const inventory = nav.getByRole("button", { name: "Inventory", exact: true });

async function signIn(username) {
  await page.goto(origin + "/inventory");
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(nav).toBeVisible();
}

try {
  expect((await page.request.get(endpoint)).status()).toBe(mode === "disabled" ? 404 : 401);
  await signIn("alice");
  if (mode === "disabled") {
    await expect(inventory).toHaveCount(0);
    await expect(page.getByRole("region", { name: "objects records" })).toBeVisible();
    expect((await page.request.get(endpoint)).status()).toBe(404);
  } else if (mode === "wrong-installation") {
    await expect(page.getByRole("alert")).toHaveText("Overlay inventory is unavailable.");
    expect((await page.request.get(endpoint)).status()).toBe(503);
  } else {
    const response = await page.request.get(endpoint);
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toBe("no-store");
    const snapshot = await response.json();
    expect(snapshot.entries.map(entry => entry.path)).toEqual(["AGENTS.md", "docs/tools.md"]);
    await expect(page.getByRole("heading", { name: "Overlay inventory" })).toBeVisible();
    await expect(page.getByText("No definitions included.", { exact: true })).toHaveCount(2);
    const summary = page.getByText("AGENTS.md", { exact: true }).last();
    await summary.press("Enter");
    await expect(page.locator("pre")).toHaveText("<script>syntheticOverlayOnly</script>");
    await expect(page.locator("script").filter({ hasText: "syntheticOverlayOnly" })).toHaveCount(0);
    await page.getByText("docs/tools.md", { exact: true }).click();
    await expect(page.getByText("This file is empty.", { exact: true })).toBeVisible();
    await page.screenshot({ path: results + "/overlay-inventory.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    const reader = await browser.newContext();
    const headers = { Origin: origin };
    expect((await page.request.post(origin + "/api/users", {
      headers, data: { username: "inventory-reader", title: "Inventory Reader", role: "reader", password },
    })).status()).toBe(200);
    expect((await reader.request.post(origin + "/api/login", {
      headers, data: { username: "inventory-reader", password },
    })).status()).toBe(200);
    expect((await reader.request.get(endpoint)).status()).toBe(403);
    const readerPage = await reader.newPage();
    await readerPage.goto(origin + "/inventory");
    await expect(readerPage.getByRole("navigation")).toBeVisible();
    await expect(readerPage.getByRole("button", { name: "Inventory", exact: true })).toHaveCount(0);
    await reader.close();
  }
  console.log("Overlay inventory passed:", mode);
} finally {
  await browser.close();
}
