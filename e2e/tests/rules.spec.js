// @ts-check
/**
 * Sprint 25 sign-off journey #3 — Rules + Alerts.
 *
 *   build rule → trigger condition → alert fires → notification received → acknowledge
 *
 * Rule construction has tight unit / integration coverage in apps/rules/tests/,
 * so this spec creates the rule via the API and exercises the headline
 * trigger / alert / acknowledge chain through the UI.
 */
const { execSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const { apiContext, reseed } = require('../fixtures/api');
const { TENANT_ADMIN_EMAIL } = require('../global-setup');

test.beforeAll(() => reseed());

const DEVICE_SERIAL = 'E2E-DEVICE-001';
const STREAM_KEY = 'temperature';
const RULE_NAME_PREFIX = 'E2E Threshold Rule';

function publishTemperature(value) {
  const script = `import os, time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="e2e-rule-pub")
c.username_pw_set("e2e-publisher", "e2e-publisher-password")
c.connect(os.environ.get("MQTT_BROKER_HOST", "mosquitto"), 1883, keepalive=10)
c.loop_start()
r = c.publish("that-place/scout/${DEVICE_SERIAL}/telemetry",
              '{"temperature": ${value}}', qos=1)
r.wait_for_publish(timeout=5)
time.sleep(0.6)
c.loop_stop()
c.disconnect()
`;
  execSync('docker-compose exec -T backend python -', { input: script, stdio: ['pipe', 'pipe', 'pipe'] });
}

async function waitForStream(api, deviceId, key) {
  for (let i = 0; i < 20; i += 1) {
    const res = await api.get(`/api/v1/devices/${deviceId}/streams/`);
    if (res.ok()) {
      const streams = await res.json();
      const match = streams.find((s) => s.key === key);
      if (match) return match;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Stream ${key} not discovered after 10s`);
}

test.describe('Rules + alerts journey', () => {
  test('rule fires on telemetry → alert visible → acknowledge updates status', async ({ page }) => {
    const ruleName = `${RULE_NAME_PREFIX} ${Date.now().toString(36)}`;
    const api = await apiContext(TENANT_ADMIN_EMAIL);

    // Locate seeded device.
    const devRes = await api.get('/api/v1/devices/');
    const devices = (await devRes.json()).results || (await devRes.json());
    const device = devices.find((d) => d.serial_number === DEVICE_SERIAL);
    expect(device).toBeTruthy();

    // Seed a low reading to auto-discover the temperature stream.
    publishTemperature(10);
    const stream = await waitForStream(api, device.id, STREAM_KEY);

    // Build the rule via the API — UI rule builder is unit-tested.
    const ruleRes = await api.post('/api/v1/rules/', {
      data: {
        name: ruleName,
        description: 'E2E threshold rule',
        is_active: true,
        condition_group_operator: 'AND',
        condition_groups: [{
          logical_operator: 'AND',
          order: 0,
          conditions: [{
            condition_type: 'stream',
            stream: stream.id,
            operator: '>',
            threshold_value: '50',
            order: 0,
          }],
        }],
        actions: [{
          action_type: 'notify',
          notification_channels: ['in_app'],
          group_ids: [],
          user_ids: [],
          message_template: '{{device_name}} temperature is {{value}}.',
        }],
      },
    });
    expect(ruleRes.ok(), `rule create failed: ${await ruleRes.text()}`).toBeTruthy();

    // Trigger: temperature crosses 50.
    publishTemperature(75);

    // Wait for alert to appear via API, then confirm via UI.
    let alertId = null;
    for (let i = 0; i < 30; i += 1) {
      const ar = await api.get('/api/v1/alerts/', { params: { status: 'active' } });
      if (ar.ok()) {
        const alerts = (await ar.json()).results || (await ar.json());
        const match = alerts.find((a) => a.rule_name === ruleName);
        if (match) { alertId = match.id; break; }
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    expect(alertId, 'alert was not created within 15s').toBeTruthy();

    // UI: confirm the alert is visible on the Active feed.
    await page.goto('/app/alerts');
    await expect(page.getByRole('cell', { name: ruleName })).toBeVisible();

    // UI: open the alert detail and acknowledge it.
    await page.goto(`/app/alerts/${alertId}`);
    await page.getByRole('button', { name: /^acknowledge$/i }).click();
    await page.getByRole('button', { name: /confirm acknowledge/i }).click();
    await expect(page.getByText(/acknowledged/i).first()).toBeVisible();

    // Verify final DB state.
    const finalRes = await api.get(`/api/v1/alerts/${alertId}/`);
    const final = await finalRes.json();
    expect(final.status).toBe('acknowledged');
    expect(final.acknowledged_by_email).toBe(TENANT_ADMIN_EMAIL);

    await api.dispose();
  });
});
