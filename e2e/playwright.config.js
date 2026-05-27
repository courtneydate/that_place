// @ts-check
const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://localhost:5173';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://localhost:8000';
const STORAGE_DIR = path.join(__dirname, 'storage');

module.exports = defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',

  globalSetup: require.resolve('./global-setup'),

  use: {
    baseURL: FRONTEND_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    storageState: path.join(STORAGE_DIR, 'tenant-admin.json'),
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'], viewport: { width: 1440, height: 900 } },
    },
  ],

  expect: {
    timeout: 10_000,
  },

  timeout: 60_000,
});

module.exports.FRONTEND_URL = FRONTEND_URL;
module.exports.BACKEND_URL = BACKEND_URL;
module.exports.STORAGE_DIR = STORAGE_DIR;
