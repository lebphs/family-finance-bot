import { defineConfig } from '@playwright/test';

// Keep the test server separate from the user's local development session.
const port = 5174;

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 390, height: 844 },
    launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
  },
  webServer: {
    command: `npm run dev -- --port ${port} --mode e2e`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    env: { VITE_LOCAL_PREVIEW: 'false', VITE_DEV_AUTH_ENABLED: 'true', VITE_DEV_TELEGRAM_USER_ID: '42', VITE_TUNNEL_HOST: 'stage4-test.trycloudflare.com' },
  },
});
