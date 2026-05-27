// @ts-check
/**
 * Sprint 25 sign-off journey #2 — Ingestion.
 *
 *   send MQTT reading → verify StreamReading → verify health update
 *
 * Publishes a single telemetry payload to the seeded That-Place v1 Scout via
 * the docker-compose backend container, then navigates the Tenant Admin UI to
 * confirm the value lands on the Streams tab and the Health tab updates.
 */
const { execSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const { apiContext, reseed } = require('../fixtures/api');
const { TENANT_ADMIN_EMAIL } = require('../global-setup');

test.beforeAll(() => reseed());

const DEVICE_SERIAL = 'E2E-DEVICE-001';

function publishTelemetry(payload) {
  // Runs inside the backend container so paho-mqtt and the MQTT creds from
  // the .env file are already available. Script is piped over stdin to avoid
  // Windows shell quoting hell with newlines / nested quotes.
  const script = `import os, time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="e2e-spec-pub")
c.username_pw_set("e2e-publisher", "e2e-publisher-password")
c.connect(os.environ.get("MQTT_BROKER_HOST", "mosquitto"), 1883, keepalive=10)
c.loop_start()
r = c.publish("that-place/scout/${DEVICE_SERIAL}/telemetry", '''${JSON.stringify(payload)}''', qos=1)
r.wait_for_publish(timeout=5)
time.sleep(0.8)
c.loop_stop()
c.disconnect()
`;
  execSync('docker-compose exec -T backend python -', {
    input: script,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
}

async function waitForReading(api, deviceId, minCount = 1) {
  for (let i = 0; i < 20; i += 1) {
    const res = await api.get(`/api/v1/devices/${deviceId}/streams/`);
    if (res.ok()) {
      const streams = await res.json();
      if (streams.length >= minCount && streams.some((s) => s.latest_value !== null)) {
        return streams;
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No streams with readings after 10s for device ${deviceId}`);
}

test.describe('Ingestion journey', () => {
  test('MQTT publish → StreamReading → device detail reflects it', async ({ page }) => {
    const api = await apiContext(TENANT_ADMIN_EMAIL);

    // Locate the seeded device id.
    const devRes = await api.get('/api/v1/devices/');
    expect(devRes.ok()).toBeTruthy();
    const devices = (await devRes.json()).results || (await devRes.json());
    const device = devices.find((d) => d.serial_number === DEVICE_SERIAL);
    expect(device, `seeded device ${DEVICE_SERIAL} missing — run seed_e2e`).toBeTruthy();

    // Publish a single payload covering temperature + battery + signal.
    const tempValue = 22.5 + Math.random() * 5;
    publishTelemetry({
      temperature: Number(tempValue.toFixed(2)),
      Relay_1: true,
      _battery: 88,
      _signal: -62,
    });

    // Backend pipeline persists the reading via Celery; wait until visible.
    const streams = await waitForReading(api, device.id);
    expect(streams.length).toBeGreaterThan(0);

    // UI: navigate to device detail, verify Streams tab shows the latest value.
    await page.goto(`/app/devices/${device.id}`);
    await page.getByRole('button', { name: /^streams$/i }).click();
    await expect(page.getByRole('cell', { name: 'temperature' }).first()).toBeVisible();
    const tempRow = page.locator('tr', { hasText: 'temperature' });
    await expect(tempRow).toContainText(/\d/);

    // UI: Health tab reflects online + battery + signal updated.
    await page.getByRole('button', { name: /^health$/i }).click();
    await expect(page.getByText(/online/i).first()).toBeVisible();
    await expect(page.getByText('88%')).toBeVisible();
    await expect(page.getByText('-62 dBm')).toBeVisible();

    await api.dispose();
  });
});
