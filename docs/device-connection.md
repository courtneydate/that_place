# Device Connection Guide

> **Audience:** Hardware operators and Tenant Admins setting up a Scout or legacy device.
> This guide covers the full process from platform registration through to a live MQTT connection.

---

## Overview

Connecting a device to That Place involves two people and three stages:

| Stage | Who | What happens |
|-------|-----|-------------|
| 1. Register | Tenant Admin | Creates the device record in the platform |
| 2. Approve | That Place Admin | Reviews and activates the device; MQTT credentials are issued automatically |
| 3. Configure | Hardware operator | Loads credentials onto the Scout firmware and connects to the broker |

A device that has not been approved cannot send data. Messages from unapproved devices are silently discarded.

---

## Stage 1 — Register the Device

Log in as **Tenant Admin** and navigate to **Devices → Register Device**.

| Field | Description |
|-------|-------------|
| **Name** | A human-readable label for this device (e.g. `Bore Pump 3 — North Paddock`) |
| **Serial Number** | The hardware serial number printed on the device. Must be unique across all tenants. |
| **Site** | The physical site where the device is deployed |
| **Device Type** | Select from the device type library (set by That Place Admin) |
| **MQTT Auth Mode** | `Username / Password` for legacy Scouts; `Client Certificate (mTLS)` for new v1 Scouts |

Click **Register**. The device is created with status **Pending** and a notification is sent to That Place Admin.

> **Auth mode tip:** If you are unsure which auth mode to select, choose **Username / Password**. You can ask That Place Admin to re-provision with certificate mode later if needed. See [Choosing an Auth Mode](#choosing-an-auth-mode) below.

---

## Stage 2 — Approval (That Place Admin)

That Place Admin receives a notification of the pending device and navigates to **Admin → Pending Devices**.

On approval:
- The device status changes to **Active**
- MQTT credentials are automatically provisioned based on the selected auth mode
- Credentials become available on the device detail page for the Tenant Admin to retrieve

If the device is **rejected**, no credentials are issued and the Tenant Admin is notified. The device can be corrected and re-submitted.

---

## Stage 3 — Configure the Scout

### 3.1 Retrieve credentials

Tenant Admin navigates to **Devices → [Device Name] → Settings → MQTT Credentials**.

**Username / Password mode:**

| Setting | Value |
|---------|-------|
| Username | `scout-{serial_number}` (e.g. `scout-FM-SCOUT-001`) |
| Password | Shown once on this page — copy it now |

**Certificate mode:**

| File | Description |
|------|-------------|
| `ca.crt` | That Place CA certificate — the Scout uses this to verify the broker |
| `device.crt` | This device's client certificate |
| `device.key` | This device's private key — **download and store securely** |

> The private key is available on this page until you mark it as delivered. Once marked delivered, it is cleared from the platform and cannot be retrieved again. Load it onto the Scout before marking it delivered.

---

### 3.2 MQTT broker connection settings

Configure these settings in the Scout firmware.

#### Username / Password (port 1883)

| Setting | Value |
|---------|-------|
| **Broker host** | As provided by That Place Admin (e.g. `mqtt.your-organisation.io`) |
| **Port** | `1883` |
| **TLS** | None |
| **Username** | `scout-{serial_number}` |
| **Password** | From credentials page (Stage 3.1) |
| **Client ID** | Recommended: use the serial number (e.g. `FM-SCOUT-001`) |
| **Keep-alive** | `60` seconds |
| **Clean session** | `false` (persistent session — re-subscribes automatically on reconnect) |

#### Client Certificate / mTLS (port 8883)

| Setting | Value |
|---------|-------|
| **Broker host** | As provided by That Place Admin |
| **Port** | `8883` |
| **TLS** | Enabled |
| **CA certificate** | Load `ca.crt` from Stage 3.1 |
| **Client certificate** | Load `device.crt` from Stage 3.1 |
| **Client private key** | Load `device.key` from Stage 3.1 |
| **Username** | Leave blank — identity comes from the certificate |
| **Password** | Leave blank |
| **Client ID** | Recommended: use the serial number (e.g. `FM-SCOUT-001`) |
| **Keep-alive** | `60` seconds |
| **Clean session** | `false` |

> The broker's own certificate is signed by the same That Place CA. The Scout will verify it using `ca.crt`. Do not disable certificate verification on the Scout.

---

### 3.3 Topics to publish

Configure the Scout to publish telemetry on the correct topic for its firmware version.

#### That Place v1 firmware (new Scouts)

| Message | Topic | Direction |
|---------|-------|-----------|
| Scout's own telemetry | `that-place/scout/{scout_serial}/telemetry` | Scout → Platform |
| Bridged device telemetry | `that-place/scout/{scout_serial}/{device_serial}/telemetry` | Scout → Platform |
| Command acknowledgement | `that-place/scout/{scout_serial}/{device_serial}/cmd/ack` | Scout → Platform |

#### Legacy v1 firmware (older Scouts)

| Message | Topic | Direction |
|---------|-------|-----------|
| Telemetry (12-channel CSV) | `fm/mm/{scout_serial}/telemetry` | Scout → Platform |
| Weatherstation data | `fm/mm/{scout_serial}/weatherstation` | Scout → Platform |
| TBox data | `fm/mm/{scout_serial}/tbox` | Scout → Platform |
| ABB drive data | `fm/mm/{scout_serial}/abb` | Scout → Platform |

#### Topics to subscribe

The Scout must subscribe to its own command namespace to receive commands from the platform:

| Firmware | Subscribe topic |
|----------|----------------|
| That Place v1 | `that-place/scout/{scout_serial}/#` |
| Legacy v1 | *(command format TBC — see hardware team)* |

> The Scout is ACL-restricted to its own serial namespace. Attempting to publish on another device's topics will be rejected by the broker.

---

### 3.4 Telemetry payload format

#### That Place v1 — JSON key-value object

Publish all stream values in a single JSON object per telemetry interval. Keys are stream identifiers; values are the current readings.

```json
{
  "soil_moisture": 42.3,
  "soil_temp": 18.7,
  "battery_voltage": 3.84,
  "_battery": 82,
  "_signal": -67
}
```

Stream keys are free-form. Any key the Scout hasn't published before will create a new stream automatically on first receipt. There is no need to pre-register stream keys.

**Reserved keys** (extracted for device health — also stored as stream readings):

| Key | Type | Description |
|-----|------|-------------|
| `_battery` | Integer, 0–100 | Battery level as a percentage. Mains-powered Scouts should send `100`. |
| `_signal` | Integer (dBm) | RSSI signal strength, e.g. `-67`. Negative values. |

If these keys are absent the corresponding health fields are not updated but data ingestion continues normally.

#### Legacy v1 — 12-value CSV string

The telemetry topic `fm/mm/{serial}/telemetry` expects a comma-separated string of exactly 12 values in this fixed order:

| Position | Stream key | Type | Example |
|----------|-----------|------|---------|
| 0 | `Relay_1` | Boolean (0/1) | `0` |
| 1 | `Relay_2` | Boolean (0/1) | `1` |
| 2 | `Relay_3` | Boolean (0/1) | `0` |
| 3 | `Relay_4` | Boolean (0/1) | `0` |
| 4 | `Analog_1` | Numeric | `3.2` |
| 5 | `Analog_2` | Numeric | `0.0` |
| 6 | `Analog_3` | Numeric | `1.5` |
| 7 | `Analog_4` | Numeric | `0.8` |
| 8 | `Digital_1` | Boolean (0/1) | `1` |
| 9 | `Digital_2` | Boolean (0/1) | `0` |
| 10 | `Digital_3` | Boolean (0/1) | `0` |
| 11 | `Digital_4` | Boolean (0/1) | `1` |

Example payload: `0,1,0,0,3.2,0.0,1.5,0.8,1,0,0,1`

Legacy devices have no battery or signal reporting. Health status is derived from time since last message only.

---

## Bridged Devices (Scout + Connected Sensors)

If sensors connect to the Scout via a local protocol (e.g. MODBUS, RS485), the Scout handles protocol translation and publishes JSON telemetry on behalf of each sensor using its own MQTT connection.

Each bridged sensor must be registered in That Place as its own device with:
- Its own serial number (the sensor's hardware ID)
- **Gateway Device** set to the parent Scout

The Scout publishes the sensor's data using the bridged topic format:

```
that-place/scout/{scout_serial}/{sensor_serial}/telemetry
```

The `{sensor_serial}` in the topic must exactly match the serial number registered in That Place for that sensor. The Scout's own MQTT credentials cover all bridged device topics — sensors do not get separate credentials.

---

## Verifying the Connection

Once the Scout is running with the correct settings:

1. Navigate to **Devices → [Device Name]** in the platform
2. The status badge should change from **Pending** to **Active** (it was already active after approval — this confirms data is flowing)
3. The **Last Seen** timestamp on the Health tab updates within the polling interval
4. The **Streams** tab populates automatically as the Scout publishes telemetry keys

If streams do not appear within 2–3 minutes of the Scout connecting, see [Troubleshooting](#troubleshooting) below.

---

## Choosing an Auth Mode

| Your situation | Recommended mode |
|----------------|-----------------|
| Legacy Scout (old firmware, `fm/mm` topics) | **Username / Password** |
| New That Place v1 Scout, firmware supports TLS client certs | **Client Certificate (mTLS)** |
| Unsure / firmware not yet confirmed | **Username / Password** — can be changed later by re-provisioning |

Certificate mode provides stronger security: the Scout's private key never leaves the device and is not transmitted during connection. It requires firmware that supports loading a CA cert, client cert, and private key into a TLS context.

---

## Troubleshooting

**Device shows Pending after approval**
The platform status badge reflects the registration state, not the connection state. If the device is approved but the Streams tab is empty, the Scout has not yet connected or published data.

**No streams appearing after Scout connects**
- Confirm the broker host and port are correct in the Scout firmware
- Confirm the username / certificate matches what is shown on the credentials page exactly — serial numbers are case-sensitive
- Check the Scout firmware logs for MQTT connection errors (auth failure, TLS handshake failure)
- For certificate mode: confirm `ca.crt` is loaded correctly — the Scout must trust the broker's certificate

**Authentication failure (password mode)**
The password is generated once at approval time. If it has been lost, ask That Place Admin to re-provision credentials for the device.

**TLS handshake failure (certificate mode)**
- Confirm all three files (`ca.crt`, `device.crt`, `device.key`) are loaded
- Confirm the private key matches the certificate (they are issued as a pair)
- Confirm the Scout's system clock is reasonably accurate — certificate validity is time-based

**Data arriving but no streams visible**
The Scout serial number in the MQTT topic must exactly match the serial number registered in That Place. A mismatch causes messages to be discarded with no error to the Scout.

**Legacy Scout — data arriving but values look wrong**
The legacy CSV payload must be exactly 12 comma-separated values in the fixed order shown in [Legacy v1 payload format](#legacy-v1--12-value-csv-string). Extra or missing values shift all subsequent fields.

---

*This document covers That Place v1 platform — MQTT ingestion pipeline.*
*Related: `SPEC.md § Feature: Data Ingestion — MQTT`, `security_risks.md § SR-01`*
