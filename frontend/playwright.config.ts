import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/e2e",
  testMatch: "**/*.spec.ts",
  outputDir: "test-results",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:3100", trace: "off", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome" } },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], defaultBrowserType: "chromium", channel: "chrome" },
    },
  ],
  webServer: {
    command: "npm run start -- --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: false,
    timeout: 120000,
    env: { NEXT_PUBLIC_MOCK: "1", NEXT_TELEMETRY_DISABLED: "1" },
  },
});
