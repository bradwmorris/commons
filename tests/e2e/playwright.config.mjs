import { defineConfig } from '@playwright/test';
import path from 'node:path';

const baseURL = process.env.COMMONS_TEST_BASE_URL;
if (!baseURL || !/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(baseURL) ||
    !process.env.COMMONS_TEST_FIXTURE || !process.env.COMMONS_TEST_RUN_ID) {
  throw new Error('Use scripts/testing/run verify: isolated local fixtures are required.');
}
const results = path.resolve(process.env.COMMONS_TEST_RESULTS);

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.mjs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  outputDir: path.join(results, 'browser'),
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(results, 'report'), open: 'never' }],
    ['json', { outputFile: path.join(results, 'browser.json') }],
  ],
  use: {
    baseURL,
    browserName: 'chromium',
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 2,
    timezoneId: 'Australia/Brisbane',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
});
