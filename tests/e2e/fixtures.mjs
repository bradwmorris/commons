import { test as base, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

export const fixture = JSON.parse(readFileSync(process.env.COMMONS_TEST_FIXTURE, 'utf8'));

export const test = base.extend({
  page: async ({ page }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await use(page);
    expect(errors, 'uncaught browser exceptions').toEqual([]);
  },
});
export { expect };

export async function login(page, username = 'bob') {
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(fixture.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Commons', exact: true })).toBeVisible();
}

export async function api(request, route, body, token = fixture.agent.token, status = 200) {
  const response = await request.fetch(`/api/${route}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Authorization: `Bearer ${token}` },
    ...(body === undefined ? {} : { data: body }),
  });
  expect(response.status(), `${route} status`).toBe(status);
  return response.json();
}

export async function apply(request, operations, token = fixture.agent.token, status = 200) {
  return api(request, 'apply', {
    contract_version: 'commons/0.1', idempotency_key: randomUUID(), operations,
  }, token, status);
}
