// @ts-check
/**
 * Sprint 25 sign-off journey #5 — Export.
 *
 *   configure export → download CSV → verify format
 *
 * Publishes a couple of readings to seed real StreamReadings, then walks the
 * Reporting page form, captures the streaming download, and asserts on the
 * CSV header and row shape.
 */
const fs = require('fs');
const { execSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const { apiContext, reseed } = require('../fixtures/api');
const { TENANT_ADMIN_EMAIL } = require('../global-setup');

test.beforeAll(() => reseed());

const DEVICE_SERIAL = 'E2E-DEVICE-001';
const DEVICE_NAME = 'E2E Scout 001';

function publishTemperature(value) {
  const script = `import os, time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="e2e-export-pub")
c.username_pw_set("e2e-publisher", "e2e-publisher-password")
c.connect(os.environ.get("MQTT_BROKER_HOST", "mosquitto"), 1883, keepalive=10)
c.loop_start()
r = c.publish("that-place/scout/${DEVICE_SERIAL}/telemetry",
              '{"temperature": ${value}}', qos=1)
r.wait_for_publish(timeout=5)
time.sleep(0.4)
c.loop_stop()
c.disconnect()
`;
  execSync('docker-compose exec -T backend python -', { input: script, stdio: ['pipe', 'pipe', 'pipe'] });
}

function localDateTimeInput(date) {
  // Format a Date for the HTML datetime-local input (no timezone suffix).
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

test.describe('Export journey', () => {
  test('configure → download CSV → verify format', async ({ page }) => {
    const api = await apiContext(TENANT_ADMIN_EMAIL);

    // Seed two readings so the export has at least two rows.
    publishTemperature(20.5);
    publishTemperature(21.5);
    // Give Celery time to persist them before configuring the export window.
    await page.waitForTimeout(2500);

    const now = new Date();
    const past = new Date(now.getTime() - 5 * 60_000);
    const future = new Date(now.getTime() + 60_000);

    await page.goto('/app/reporting');
    await page.getByLabel(/from \(exclusive\)/i).fill(localDateTimeInput(past));
    await page.getByLabel(/to \(inclusive\)/i).fill(localDateTimeInput(future));

    // Locate the seeded device block, expand it, then tick temperature.
    // Other specs may have left stray devices in the tenant; pin to serial.
    const deviceBlock = page.locator('div').filter({ hasText: DEVICE_SERIAL }).first();
    await deviceBlock.getByRole('button', { name: /expand streams/i }).click();
    await page.getByRole('checkbox', { name: /temperature/i }).check();

    // Capture the streaming download.
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /download csv/i }).click();
    const download = await downloadPromise;

    const tmp = await download.path();
    expect(tmp).toBeTruthy();
    const csv = fs.readFileSync(tmp, 'utf8');

    const [header, ...rows] = csv.trim().split(/\r?\n/);
    expect(header.toLowerCase()).toContain('timestamp');
    expect(header.toLowerCase()).toContain('site_name');
    expect(header.toLowerCase()).toContain('device_name');
    expect(header.toLowerCase()).toContain('stream_label');
    expect(header.toLowerCase()).toContain('value');
    expect(rows.length).toBeGreaterThanOrEqual(2);
    expect(rows.some((r) => r.includes(DEVICE_NAME))).toBeTruthy();

    await api.dispose();
  });
});
