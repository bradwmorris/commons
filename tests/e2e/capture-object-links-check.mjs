import { chromium, expect } from "@playwright/test";
import fs from "node:fs";
const { origin, password } = JSON.parse(fs.readFileSync(process.env.COMMONS_ATOMIC_FIXTURE));
const results = process.env.COMMONS_ATOMIC_RESULTS;
const fixture = JSON.parse(fs.readFileSync(results + "/capture-object-links.json"));
const browser = await chromium.launch({ executablePath: process.env.COMMONS_CHROMIUM_BINARY });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(origin + "/threads/" + fixture.thread);
  await page.getByLabel("Username", { exact: true }).fill("alice");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const related = page.getByRole("region", { name: "Related objects" });
  await expect(related.getByRole("link", { name: "Object links read fixture" })).toHaveCount(2);
  await expect(related.getByRole("link", { name: "Object links created Note" })).toBeVisible();
  await related.scrollIntoViewIfNeeded();
  await page.screenshot({ path: results + "/thread-object-links.png" });
  await related.locator('a[href="/traces/' + fixture.write_trace + '"]').click();
  await expect(page).toHaveURL(origin + "/traces/" + fixture.write_trace);
  await expect(related.getByText("Created · supplied reference")).toBeVisible();
  await expect(related.getByText("Updated · supplied reference")).toBeVisible();
  await related.scrollIntoViewIfNeeded();
  await page.screenshot({ path: results + "/trace-object-links.png" });
  await related.getByRole("link", { name: "Object links created Note" }).click();
  await expect(page).toHaveURL(origin + "/objects/" + fixture.note_id);
  await page.goto(origin + "/traces/" + fixture.read_trace);
  await expect(related.getByText("Read · supplied reference")).toBeVisible();
} finally {
  await browser.close();
}
