import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  use: { baseURL: "http://localhost:3006", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 3006",
    url: "http://localhost:3006",
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
    env: { IAM_ADAPTER: "mock" },
  },
});
