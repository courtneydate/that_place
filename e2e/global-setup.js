// @ts-check
/**
 * Playwright global setup.
 *
 * Runs once before any test. Verifies the backend is reachable, reseeds the
 * deterministic E2E fixture via the management command if asked, then logs in
 * as the two seeded users (Tenant Admin + That Place Admin) and writes their
 * authenticated browser storage to disk for individual specs to reuse.
 *
 * Per-spec specs that need an unauthenticated session simply override
 * `storageState` to `undefined`.
 */
const fs = require('fs');
const path = require('path');
const { chromium, request } = require('@playwright/test');
const { FRONTEND_URL, BACKEND_URL } = require('./playwright.config');

const PASSWORD = process.env.E2E_PASSWORD || 'e2e-password';
const TP_ADMIN_EMAIL = 'e2e_tp_admin@test.thatplace.local';
const TENANT_ADMIN_EMAIL = 'e2e_tenant_admin@test.thatplace.local';

const STORAGE_DIR = path.join(__dirname, 'storage');

async function waitForBackend() {
  const ctx = await request.newContext();
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    try {
      const res = await ctx.get(`${BACKEND_URL}/api/v1/auth/login/`, { failOnStatusCode: false });
      if (res.status() === 405 || res.status() === 400) {
        await ctx.dispose();
        return;
      }
    } catch (_) {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  await ctx.dispose();
  throw new Error(`Backend not reachable at ${BACKEND_URL} after 60s — is docker-compose up?`);
}

async function saveLogin(email) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${FRONTEND_URL}/login`);
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole('button', { name: /log in|sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 });
  const filePath = path.join(STORAGE_DIR, `${email === TP_ADMIN_EMAIL ? 'tp-admin' : 'tenant-admin'}.json`);
  await ctx.storageState({ path: filePath });
  await browser.close();
}

module.exports = async () => {
  fs.mkdirSync(STORAGE_DIR, { recursive: true });
  await waitForBackend();
  await saveLogin(TENANT_ADMIN_EMAIL);
  await saveLogin(TP_ADMIN_EMAIL);
};

module.exports.PASSWORD = PASSWORD;
module.exports.TP_ADMIN_EMAIL = TP_ADMIN_EMAIL;
module.exports.TENANT_ADMIN_EMAIL = TENANT_ADMIN_EMAIL;
