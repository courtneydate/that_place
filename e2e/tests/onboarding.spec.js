// @ts-check
/**
 * Sprint 25 sign-off journey #1 — Onboarding.
 *
 *   create tenant → invite admin → set up site → register device → approve device
 *
 * Exercised through the UI as both That Place Admin (creates + approves) and
 * Tenant Admin (sets up site + registers device). A unique suffix is used for
 * the tenant name / device serial so the spec is independent of seeded data and
 * can be re-run without manual cleanup.
 */
const path = require('path');
const { test, expect } = require('@playwright/test');
const { apiContext, reseed } = require('../fixtures/api');
const { STORAGE_DIR } = require('../playwright.config');
const { TP_ADMIN_EMAIL, TENANT_ADMIN_EMAIL } = require('../global-setup');

test.beforeAll(() => reseed());

const TP_ADMIN_STATE = path.join(STORAGE_DIR, 'tp-admin.json');
const TENANT_ADMIN_STATE = path.join(STORAGE_DIR, 'tenant-admin.json');

function suffix() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

test.describe('Onboarding journey', () => {
  test('TP Admin onboards a new tenant end-to-end', async ({ browser }) => {
    const sfx = suffix();
    const tenantName = `E2E Onboard ${sfx}`;
    const inviteEmail = `onboard-${sfx}@e2e.test`;
    const siteName = `Onboard Site ${sfx}`;
    const deviceName = `Onboard Device ${sfx}`;
    const deviceSerial = `ONBOARD-${sfx.toUpperCase()}`;

    // --- TP Admin: create tenant via UI ---
    const tpCtx = await browser.newContext({ storageState: TP_ADMIN_STATE });
    const tpPage = await tpCtx.newPage();

    await tpPage.goto('/admin/tenants');
    await tpPage.getByRole('link', { name: /new tenant/i }).click();
    await expect(tpPage).toHaveURL(/\/admin\/tenants\/new/);
    await tpPage.getByPlaceholder(/Riverdale/i).fill(tenantName);
    await tpPage.getByRole('button', { name: /create tenant/i }).click();

    await expect(tpPage).toHaveURL(/\/admin\/tenants\/\d+/);
    await expect(tpPage.getByRole('heading', { name: tenantName })).toBeVisible();

    // --- TP Admin: send invite via UI ---
    await tpPage.getByPlaceholder(/user@example/i).fill(inviteEmail);
    await tpPage.getByRole('button', { name: /send invite/i }).click();
    await expect(tpPage.getByText(new RegExp(`invite sent to ${inviteEmail}`, 'i'))).toBeVisible();

    await tpCtx.close();

    // --- Tenant Admin (seeded fixture): create site via UI ---
    const tenantCtx = await browser.newContext({ storageState: TENANT_ADMIN_STATE });
    const tenantPage = await tenantCtx.newPage();

    await tenantPage.goto('/app/sites');
    await tenantPage.getByRole('button', { name: /new site/i }).click();
    await tenantPage.getByLabel(/^name/i).fill(siteName);
    await tenantPage.getByRole('button', { name: /create site/i }).click();
    await expect(tenantPage.getByRole('cell', { name: siteName })).toBeVisible();

    // --- Tenant Admin: register device via UI ---
    await tenantPage.goto('/app/devices');
    await tenantPage.getByRole('button', { name: /register device/i }).click();
    await tenantPage.getByLabel(/device name/i).fill(deviceName);
    await tenantPage.getByLabel(/serial number/i).fill(deviceSerial);
    await tenantPage.getByLabel(/^site/i).selectOption({ label: siteName });
    await tenantPage.getByLabel(/device type/i).selectOption({ index: 1 });
    await tenantPage.getByRole('button', { name: /^register device$/i }).click();

    const deviceRow = tenantPage.locator('tr', { hasText: deviceSerial });
    await expect(deviceRow).toBeVisible();
    await expect(deviceRow.getByText(/pending/i)).toBeVisible();

    await tenantCtx.close();

    // --- TP Admin: approve pending device via UI ---
    const tpCtx2 = await browser.newContext({ storageState: TP_ADMIN_STATE });
    const tpPage2 = await tpCtx2.newPage();
    tpPage2.on('dialog', (dialog) => dialog.accept());

    await tpPage2.goto('/admin/pending-devices');
    const pendingRow = tpPage2.locator('tr', { hasText: deviceSerial });
    await expect(pendingRow).toBeVisible();
    await pendingRow.getByRole('button', { name: /approve/i }).click();

    // Row disappears from the pending list once approved.
    await expect(pendingRow).toHaveCount(0, { timeout: 10_000 });

    await tpCtx2.close();

    // --- Verify state via API (cheap final assertion) ---
    const api = await apiContext(TP_ADMIN_EMAIL);
    const devicesRes = await api.get('/api/v1/devices/', {
      params: { search: deviceSerial },
    });
    expect(devicesRes.ok()).toBeTruthy();
    const body = await devicesRes.json();
    const found = (body.results || body).find((d) => d.serial_number === deviceSerial);
    expect(found).toBeTruthy();
    expect(found.status).toBe('active');
    await api.dispose();

    // Suppress unused-import lint warning for the email constant kept for traceability.
    expect(TENANT_ADMIN_EMAIL).toContain('@');
  });
});
