import { test, expect, login } from './fixtures.mjs';
import { randomUUID } from 'node:crypto';

test('shared comparisons show exact versions, both outputs, files and incomplete states', async ({ page, browser }, info) => {
  await login(page, 'bob');
  const call = async (path, body) => {
    const response = await page.request.fetch(`/api/${path}`, { method: body ? 'POST' : 'GET', headers: { Origin: new URL(page.url()).origin }, ...(body ? { data: body } : {}) });
    expect(response.status(), await response.text()).toBe(200); return response.json();
  };
  const write = operation => call('evals', { contract_version: 'commons.evals/1', idempotency_key: randomUUID(), operation });
  await expect(page.getByRole('button', { name: 'Evals', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Comparisons', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Evals', exact: true }).click();
  await page.getByRole('button', { name: 'New eval', exact: true }).click();
  const title = `Lantern outreach brief ${randomUUID().slice(0, 4)}`;
  await page.getByLabel('Name', { exact: true }).fill(title);
  await page.getByLabel('Task or question').fill('Produce briefing.md from the same supplied brief. Do not send outreach.');
  await page.getByRole('button', { name: 'Save eval', exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  const testId = page.url().split('/').at(-1);
  const run = await write({ op: 'create_run', test_id: testId, test_revision: 1, context_bundle: 'Synthetic knowledge: Lantern values developer onboarding.' });
  await page.reload();
  await expect(page.getByText('No output yet.')).toHaveCount(2);
  await page.screenshot({ path: info.outputPath('eval-pending.png') });
  const attempt = { status: 'failed', output: '', error: 'Synthetic client interrupted', session_id: 'fixture-without', isolation: 'unsupported', evidence: 'Deterministic fixture; no external agent executed.', files: [], links: [] };
  await write({ op: 'append_attempt', run_id: run.id, expected_revision: 1, arm: 'without', attempt });
  await page.reload();
  await expect(page.getByText('Synthetic client interrupted').first()).toBeVisible();
  await page.screenshot({ path: info.outputPath('eval-partial.png') });
  for (const [revision, arm, output] of [[2, 'without', 'Lead with a concise introduction.'], [3, 'with', 'Lead with the developer onboarding opportunity.']]) {
    await write({ op: 'append_attempt', run_id: run.id, expected_revision: revision, arm, attempt: { ...attempt, status: 'completed', error: '', session_id: `fixture-${arm}`, isolation: 'unverified', output, files: [{ name: `${arm}-briefing.md`, content: `# Synthetic briefing\n${output}\n` }] } });
  }
  await write({ op: 'revise_test', test_id: testId, expected_revision: 1, title, request: 'New request, not this saved run.', configuration: {} });
  await page.goto(`/eval-runs/${run.id}`);
  await expect(page.getByText('Produce briefing.md from the same supplied brief. Do not send outreach.', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Without Commons', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'With Commons', exact: true })).toBeVisible();
  const pair = page.locator('.eval-pair');
  await expect(pair.getByText('Lead with a concise introduction.', { exact: true })).toBeVisible();
  await expect(pair.getByText('Lead with the developer onboarding opportunity.', { exact: true })).toBeVisible();
  const filePath = await pair.getByRole('link', { name: 'with-briefing.md', exact: true }).getAttribute('href');
  const file = await page.request.get(filePath);
  expect(file.status()).toBe(200); expect(await file.text()).toBe('# Synthetic briefing\nLead with the developer onboarding opportunity.\n');
  await expect(page.getByText(/Starting configuration|knowledge bundle|Isolation:|Execution evidence|Run state|All saved attempts|Test version/)).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('eval-paired.png') });
  const other = await browser.newContext(); const reader = await other.newPage();
  await login(reader, 'reader'); await reader.goto(`/eval-runs/${run.id}`);
  await expect(reader.locator('.eval-pair').getByText('Lead with the developer onboarding opportunity.', { exact: true })).toBeVisible();
  expect((await reader.request.get(filePath)).status()).toBe(200);
  await reader.goto('/evals'); await expect(reader.getByRole('button', { name: 'New eval', exact: true })).toHaveCount(0);
  await other.close();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'With Commons', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: info.outputPath('eval-narrow.png'), fullPage: true });
  expect((await call(`eval-runs/${run.id}`)).attempts[0].payload.error).toBe('Synthetic client interrupted');
  await page.getByRole('heading', { name: 'With Commons', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('eval-narrow-treatment.png') });
});
