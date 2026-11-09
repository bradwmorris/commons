// Invoked by the isolated verification harness against a real restarted API.
import { chromium } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import assert from 'node:assert/strict';
const base = process.env.COMMONS_TEST_BASE_URL;
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw new Error('Isolated harness required');
const fixture = JSON.parse(readFileSync(process.env.COMMONS_TEST_FIXTURE, 'utf8'));
const accent = process.env.COMMONS_TEST_ACCENT;
const response = await fetch(`${base}/api/appearance.css`);
assert.equal(response.status, 200);
assert.match(response.headers.get('content-type'), /^text\/css/);
assert.equal(response.headers.get('cache-control'), 'no-store');
const css = await response.text();
assert.equal(css.length > 0, Boolean(accent));
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByLabel('Username', { exact: true }).fill('bob');
  await page.getByLabel('Password', { exact: true }).fill(fixture.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  if (accent) {
    assert.equal(await page.locator('.nav-button.active').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(28, 29, 32)');
    await page.getByRole('button', { name: 'Notes', exact: true }).hover();
    assert.equal(await page.getByRole('button', { name: 'Notes', exact: true }).evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(23, 24, 27)');
  }
  await page.getByRole('button', { name: 'New object', exact: true }).click();
  const title = page.getByLabel('Title', { exact: true });
  await title.fill('Synthetic appearance check');
  await title.focus();
  const style = await page.locator('.primary').evaluate(e => ({ background: getComputedStyle(e).backgroundColor, color: getComputedStyle(e).color }));
  assert.equal(style.background, accent || 'rgb(231, 231, 233)');
  if (accent) {
    assert.equal(style.color, 'rgb(0, 0, 0)');
    assert.equal(await title.evaluate(e => getComputedStyle(e).outlineColor), accent);
    assert.match(await page.locator('body').evaluate(e => getComputedStyle(e).fontFamily), /monospace/);
  }
  await page.screenshot({ path: join(process.env.COMMONS_TEST_RESULTS, `appearance-${process.env.COMMONS_TEST_APPEARANCE_LABEL}.png`) });
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').count(), 0);
  assert.deepEqual(errors, []);
} finally { await browser.close(); }
console.log('Appearance configuration verified:', process.env.COMMONS_TEST_APPEARANCE_LABEL);
