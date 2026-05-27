// @ts-check
/**
 * Thin API client + setup helpers for E2E.
 *
 * Specs use this to short-circuit slow UI flows when arranging preconditions
 * (e.g. creating a device to test the alert flow). The user-facing journey
 * being tested is always exercised through the browser; supporting state is
 * created via the API.
 */
const { execSync } = require('child_process');
const { request } = require('@playwright/test');
const { BACKEND_URL } = require('../playwright.config');

function reseed() {
  // Reset the deterministic E2E fixture between spec files so cross-spec
  // pollution (e.g. throwaway tenants from onboarding) doesn't bleed into
  // later specs or the firefox pass.
  execSync('docker-compose exec -T backend python manage.py seed_e2e', {
    stdio: ['ignore', 'ignore', 'pipe'],
  });
}

const PASSWORD = process.env.E2E_PASSWORD || 'e2e-password';

async function login(email, password = PASSWORD) {
  const ctx = await request.newContext({ baseURL: BACKEND_URL });
  const res = await ctx.post('/api/v1/auth/login/', {
    data: { email, password },
  });
  if (!res.ok()) {
    throw new Error(`Login failed for ${email}: ${res.status()} ${await res.text()}`);
  }
  const { access } = await res.json();
  await ctx.dispose();
  return access;
}

async function apiContext(email) {
  const token = await login(email);
  return request.newContext({
    baseURL: BACKEND_URL,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
}

module.exports = { login, apiContext, reseed, PASSWORD, BACKEND_URL };
