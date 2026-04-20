import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from '@playwright/test';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, '..', '..');
const apiDir = path.join(repoRoot, 'services', 'api');

const apiPort = process.env.SURVEY_E2E_API_PORT ?? '8100';
const webPort = process.env.SURVEY_E2E_WEB_PORT ?? '5270';
const webBaseUrl = `http://127.0.0.1:${webPort}`;
const apiBaseUrl = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: {
    timeout: 15_000,
  },
  reporter: 'list',
  use: {
    baseURL: webBaseUrl,
    browserName: 'chromium',
    headless: true,
    launchOptions: {
      executablePath: '/usr/bin/google-chrome',
      args: ['--no-sandbox', '--disable-gpu', '--no-first-run'],
    },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `UV_CACHE_DIR=/tmp/agentic-survey-uv-cache SURVEY_LLM_ENABLED=false SURVEY_PUBLIC_BASE_URL=${webBaseUrl} SURVEY_FRONTEND_ORIGIN=${webBaseUrl} uv run uvicorn agentic_survey.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: apiDir,
      url: `${apiBaseUrl}/api/healthz`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: `SURVEY_API_PROXY_TARGET=${apiBaseUrl} npm run preview -- --host 127.0.0.1 --port ${webPort}`,
      cwd: currentDir,
      url: `${webBaseUrl}/api/system/context`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
