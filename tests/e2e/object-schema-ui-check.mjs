// Read-only journeys: exercise the actual installed schema and existing records.
// Optional UI_STATIC_ROOT previews a reviewed web build against the same API.
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const origins = process.argv.slice(2);
if (!origins.length) throw new Error('Pass the explicitly selected installation origin(s).');
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
try {
  for (const origin of origins) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage(); const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin); // Establish the installation's ordinary local session.
    if (process.env.UI_STATIC_ROOT) await page.route(`${origin}/**`, async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname.startsWith('/api/')) return route.continue();
      const file = path.join(process.env.UI_STATIC_ROOT, pathname.startsWith('/assets/') ? pathname : '/index.html');
      const contentType = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
      return route.fulfill({ body: fs.readFileSync(file), contentType });
    });
    const schemaResponse = await page.request.get(`${origin}/api/schema`); expect(schemaResponse.ok()).toBe(true);
    const schema = await schemaResponse.json();
    const tables = [...new Set(schema.columns.map(column => column.table))];
    await page.goto(`${origin}/schema`);
    if (process.env.UI_SCREENSHOT_DIR) { await expect(page.getByRole('table', { name: 'objects columns' })).toBeVisible(); await page.screenshot({ path: path.join(process.env.UI_SCREENSHOT_DIR, `schema-${new URL(origin).port}.png`) }); }
    await expect(page.getByRole('navigation', { name: 'Schema tables' }).getByRole('link')).toHaveCount(tables.length);
    for (const table of tables) {
      await page.getByRole('navigation', { name: 'Schema tables' }).getByRole('link', { name: new RegExp(`^${table} `) }).click();
      await expect(page.getByRole('table', { name: `${table} columns` }).locator('tbody tr')).toHaveCount(schema.columns.filter(column => column.table === table).length);
    }
    await page.reload(); await expect(page.getByRole('table', { name: `${tables.at(-1)} columns` })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.setViewportSize({ width: 1280, height: 900 });
    let inspected = 0; let artifactReaders = 0;
    for (const kind of ['note', 'source', 'entity', 'theme', 'event', 'task']) {
      const response = await page.request.get(`${origin}/api/objects?kind=${kind}&limit=5`); expect(response.ok()).toBe(true);
      const { objects } = await response.json(); if (!objects.length) continue;
      const object = objects[0]; await page.goto(`${origin}/objects/${object.id}`);
      const copy = page.locator('.detail-object-id').getByRole('button', { name: `Copy Object ID ${object.id}`, exact: true });
      await copy.click(); await expect(copy).toHaveAttribute('data-copy-state', 'copied');
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(object.id);
      await expect(page.getByRole('heading', { name: /^Connections \(\d+\)$/ })).toHaveCount(1);
      await expect(page.locator('summary').filter({ hasText: /Record details|History and preservation|Correct evidence|Provenance|Add document or image|^Activity / })).toHaveCount(0);
      await expect(page.locator('input[type="file"]')).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'Evidence artifacts', exact: true })).toHaveCount(0);
      if (kind === 'note' && process.env.UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.UI_SCREENSHOT_DIR, `object-${new URL(origin).port}.png`) });
      const artifactLink = page.locator('.artifact-workspace a[href*="/artifacts/"]').first();
      if (await artifactLink.count()) { if (!await artifactLink.isVisible()) await artifactLink.locator('xpath=ancestor::details[1]').locator('summary').click(); await artifactLink.click(); await expect(page.locator('.artifact-reader')).toBeVisible(); artifactReaders++; }
      inspected++;
    }
    await page.goto(`${origin}/objects`); await expect(page.locator('.record').first()).toBeVisible();
    expect(await page.locator('.record').first().evaluate(element => element.getBoundingClientRect().height)).toBe(50);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.locator('.record').first().evaluate(element => element.getBoundingClientRect().height)).toBe(46);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    expect(errors).toEqual([]);
    console.log(JSON.stringify({ origin, tables: tables.length, objectKindsInspected: inspected, artifactReaders, clipboard: 'passed', compactRows: 'passed', errors }));
    await context.close();
  }
} finally { await browser.close(); }
