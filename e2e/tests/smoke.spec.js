// @ts-check
const path = require('path');
const { test, expect } = require('@playwright/test');
const { STORAGE_DIR } = require('../playwright.config');

test.describe('Harness smoke', () => {
  test('tenant admin lands on the tenant UI', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/app\//);
    await expect(page.getByRole('heading', { name: /users/i })).toBeVisible();
  });

  test('that place admin lands on the admin UI', async ({ browser }) => {
    const ctx = await browser.newContext({
      storageState: path.join(STORAGE_DIR, 'tp-admin.json'),
    });
    const page = await ctx.newPage();
    await page.goto('/');
    await expect(page).toHaveURL(/\/admin\/tenants/);
    await expect(page.getByRole('heading', { name: /tenants/i })).toBeVisible();
    await ctx.close();
  });
});
