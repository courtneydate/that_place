// @ts-check
/**
 * Sprint 25 sign-off journey #4 — Commands.
 *
 *   send command → ack received → history logged
 *
 * Sends a command through the UI then publishes a matching MQTT `cmd/ack`
 * message via the e2e-publisher dynsec client. The command history table
 * should reflect the acknowledgement.
 */
const { execSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const { apiContext, reseed } = require('../fixtures/api');
const { TENANT_ADMIN_EMAIL } = require('../global-setup');

test.beforeAll(() => reseed());

const DEVICE_SERIAL = 'E2E-DEVICE-001';
const COMMAND_NAME = 'set_relay';

function publishAck() {
  const script = `import os, time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="e2e-cmd-ack")
c.username_pw_set("e2e-publisher", "e2e-publisher-password")
c.connect(os.environ.get("MQTT_BROKER_HOST", "mosquitto"), 1883, keepalive=10)
c.loop_start()
r = c.publish("that-place/scout/${DEVICE_SERIAL}/cmd/ack",
              '{"command": "${COMMAND_NAME}", "status": "ok"}', qos=1)
r.wait_for_publish(timeout=5)
time.sleep(0.5)
c.loop_stop()
c.disconnect()
`;
  execSync('docker-compose exec -T backend python -', { input: script, stdio: ['pipe', 'pipe', 'pipe'] });
}

test.describe('Commands journey', () => {
  test('UI send → MQTT ack → history shows acknowledged', async ({ page }) => {
    const api = await apiContext(TENANT_ADMIN_EMAIL);
    const devRes = await api.get('/api/v1/devices/');
    const devices = (await devRes.json()).results || (await devRes.json());
    const device = devices.find((d) => d.serial_number === DEVICE_SERIAL);
    expect(device).toBeTruthy();

    await page.goto(`/app/devices/${device.id}`);
    await page.getByRole('button', { name: /^commands$/i }).click();

    // Select the `set_relay` command and send with default param value.
    await page.getByRole('button', { name: /set relay/i }).first().click();
    await page.getByRole('button', { name: /send command/i }).click();
    await expect(page.getByText(/command .* sent/i)).toBeVisible({ timeout: 20_000 });

    // History table picks up the new entry with status 'sent'.
    const cmdRow = page.locator('tr', { hasText: COMMAND_NAME });
    await expect(cmdRow).toBeVisible();
    await expect(cmdRow.getByText('sent')).toBeVisible();

    // Publish the ack message — Celery + ingestion router updates the log.
    publishAck();

    // The React Query cache won't auto-refetch in the test's lifetime, so
    // reload the page to pull the updated history.
    await page.waitForTimeout(2000);
    await page.reload();
    await page.getByRole('button', { name: /^commands$/i }).click();

    const ackedRow = page.locator('tr', { hasText: COMMAND_NAME });
    await expect(ackedRow.getByText('acknowledged')).toBeVisible({ timeout: 15_000 });

    await api.dispose();
  });
});
