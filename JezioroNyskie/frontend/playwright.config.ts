import { existsSync } from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

// Dane modelu nie są w git: bez nich testy się pomijają (patrz e2e/smoke.spec.ts).
export const HAS_MODEL = existsSync(new URL('../data/processed/model/all/model_meta.json', import.meta.url));

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:4173', ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 }, locale: 'pl-PL' },
  webServer: [
    {
      command: 'uv run uvicorn app.main:app --port 8000',
      cwd: '../backend',
      env: { MIELIZNA_LIVE: '0' },
      url: 'http://localhost:8000/api/meta',
      reuseExistingServer: true,
      timeout: 180_000,
    },
    {
      command: 'npm run build && npx vite preview --port 4173 --strictPort',
      url: 'http://localhost:4173',
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
});
