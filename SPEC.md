# PROJECT SPEC — That Place

> **Version:** 5.1
> **Last Updated:** 2026-03-19
> **Author:** Courtney
> **Status:** Active — do not modify without discussion

---

## 1. Project Identity

### What is this?
That Place is an IoT monitoring, control, and automation platform. It ingests multiple data streams — from smart sensors, dumb field hardware, and third-party APIs — and turns them into intelligent, automated decisions.

**Core platform capabilities: Monitor · Control · Automate**

### What problem does it solve?
Asset and operations teams managing distributed physical infrastructure (irrigation systems, environmental sensors, utility assets) need a single platform to see what's happening, respond to it, and automate repetitive decisions. The current solution is a clunky .NET system with hardcoded limitations — That Place v1 is the modern rebuild.

### Who is it for?
- **Primary:** Local councils and managers of green spaces
- **Secondary:** Agriculture — irrigation, soil monitoring, livestock
- **Tertiary:** Industries with distributed asset monitoring needs, environmental monitoring organisations

### Business Model
B2B — sold to organisations on a subscription basis. Hardware (That Place Scout and other gateway devices) also sold on subscription.

### Tech Stack

| Layer           | Technology                              |
|-----------------|-----------------------------------------|
| Frontend (web)  | React (Vite) — primary, desktop-first   |
| Frontend (mobile) | React Native (Expo) — Phase 6, secondary |
| Backend         | Django + DRF                            |
| Database        | PostgreSQL                              |
| Hosting         | Any Linux server — AWS EC2 (ap-southeast-2) preferred, self-hosted VPS supported |
| Auth            | JWT (SimpleJWT)                         |
| Storage         | S3-compatible object storage — AWS S3 (preferred) or MinIO (self-hosted) |
| MQTT Broker     | Mosquitto (local dev + self-hosted prod) or AWS IoT Core (AWS prod) |
| Email           | Any SMTP provider — AWS SES (preferred), Mailgun, Postmark, or self-hosted |
| Task Queue      | Celery + Redis                          |
| Charting        | ApexCharts (`apexcharts` + `react-apexcharts`) |
| CI/CD           | GitHub Actions                          |
| Containers      | Docker + Docker Compose                 |

---

## 2. Architecture & Constraints

### Core Design Philosophy
> **Everything must be dynamic and configurable. Nothing is hardcoded.**

The existing .NET platform failed to grow because it was built feature-by-feature with assumptions baked into the code. Every field, stream key, device type, command, data source, and notification channel in That Place must be defined through configuration — not code. This is the primary architectural principle and must be respected in every implementation decision.

### Project Structure

```
that_place/
├── backend/
│   ├── apps/
│   │   ├── accounts/        # User auth, tenants, tenant-user relationships, notification groups
│   │   ├── devices/         # Device type library, device registry, streams, health, provisioning
│   │   ├── ingestion/       # MQTT ingestion pipeline
│   │   ├── integrations/    # 3rd-party API provider library, data sources, polling
│   │   ├── readings/        # Raw stream data storage and retrieval, CSV export
│   │   ├── rules/           # Rule builder, conditions, actions, audit trail
│   │   ├── alerts/          # Alert generation and management
│   │   ├── dashboards/      # Dashboard and widget configuration
│   │   ├── notifications/   # In-app, email, SMS, push delivery
│   │   └── feeds/           # Feed providers (API-polled channels) + reference datasets (admin-managed lookup tables)
│   ├── config/              # Django settings (base, dev, prod, test)
│   ├── requirements/        # Split requirements files
│   └── manage.py
├── frontend/                # React web app (primary)
│   ├── src/
│   │   ├── components/      # Reusable UI components
│   │   ├── pages/           # Page-level components (route targets)
│   │   ├── layouts/         # Layout wrappers (sidebar, topbar, etc.)
│   │   ├── services/        # API client, auth
│   │   ├── hooks/           # Custom hooks
│   │   └── theme/           # Semantic colour tokens, typography
│   ├── index.html
│   └── vite.config.js
├── mobile/                  # React Native app (Phase 6)
│   ├── src/
│   └── app.json
├── infrastructure/
│   ├── docker-compose.yml
│   ├── Dockerfile.backend
│   └── nginx/
├── docs/
├── CLAUDE.md
└── SPEC.md
```

### Data Hierarchy

```
Tenant
  └── Site(s)
        └── Device(s)          ← includes Scout gateway devices
              ├── Stream(s)    ← auto-discovered dynamically
              │     └── StreamReading(s)
              └── DeviceHealth
```

Devices bridged by a Scout are registered as their own Device records with a reference to the Scout that transmits their data. From the platform's perspective, all devices are equal — the Scout is simply a connectivity layer.

### Two-Tier Admin Model

| Level | Role | Responsibilities |
|-------|------|-----------------|
| Platform | That Place Admin | Manage Device Type library, approve device provisioning, manage 3rd-party API library, access all tenants |
| Tenant | Tenant Admin | Register devices, configure streams, build rules, manage users, manage notification groups |

### That Place Hardware Family

| Device | Purpose | MVP |
|--------|---------|-----|
| Scout | Edge gateway — bridges dumb/local hardware to cloud via MQTT. Manages multiple connected devices. | Yes |
| Runner | Autonomous edge device — stores and executes rules/schedules locally for offline operation. | No (Phase 4) |

### MQTT Topic Structure

All Scout-to-cloud communication uses the following topic structure:

```
that-place/scout/{scout_serial}/telemetry
that-place/scout/{scout_serial}/health
that-place/scout/{scout_serial}/{device_serial}/telemetry
that-place/scout/{scout_serial}/{device_serial}/health
that-place/scout/{scout_serial}/cmd/{command_name}
that-place/scout/{scout_serial}/{device_serial}/cmd/{command_name}
that-place/scout/{scout_serial}/{device_serial}/cmd/ack
```

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `.../telemetry` | Scout → Cloud | Scout's own telemetry — all stream values in one JSON payload |
| `.../health` | Scout → Cloud | Scout's own health — **Phase 2 only** (MVP uses `_battery`/`_signal` in telemetry payload) |
| `.../{device_serial}/telemetry` | Scout → Cloud | Telemetry from a connected device — all stream values in one JSON payload |
| `.../{device_serial}/health` | Scout → Cloud | Health data for a connected device — **Phase 2 only** |
| `.../cmd/{command_name}` | Cloud → Scout | Command sent directly to the Scout |
| `.../{device_serial}/cmd/{command_name}` | Cloud → Scout | Command for a connected device — Scout routes it |
| `.../{device_serial}/cmd/ack` | Scout → Cloud | Confirmation that a command was received and executed |

**Scout subscribes to:** `that-place/scout/{scout_serial}/#`
**Backend subscribes to:** `that-place/scout/+/#`

**Telemetry payloads — stream values are sent as a JSON key-value object in a single message per device per interval:**

v1 Scout own telemetry — includes `_battery` and `_signal` as reserved health keys alongside regular stream data:
```json
{ "Relay_1": 0, "Relay_2": 1, "Relay_3": 0, "Relay_4": 0, "Analog_1": 3.2, "Analog_2": 0.0, "Analog_3": 1.5, "Analog_4": 0.8, "Digital_1": 1, "Digital_2": 0, "Digital_3": 0, "Digital_4": 1, "_battery": 82, "_signal": -67 }
```

`_battery` and `_signal` are reserved key names — they are extracted from the payload to update `DeviceHealth` and are also stored as virtual `StreamReading` records so they are available to the rule engine and dashboard charts. Mains-powered Scouts always send `_battery: 100`. Both keys are optional — if absent the corresponding health fields are not updated.

v1 bridged device telemetry (any device type including MODBUS — Scout handles protocol translation, That Place sees JSON):
```json
{ "temperature": 23.4, "humidity": 60.1, "pressure": 1013.2 }
```

**Health topic — Phase 2:** The `.../health` and `.../{device_serial}/health` topics are deferred to Phase 2. In MVP, battery and signal data are carried in the Scout's own telemetry payload using the `_battery` and `_signal` reserved keys. `last_seen_at` is updated on every received message of any type.

**Legacy v1 health:** Legacy Scouts have no battery or signal data. `DeviceHealth.last_seen_at` is updated on every telemetry message received. `battery_level` and `signal_strength` remain null for legacy devices.

**Dual-format topic support (legacy migration):**

The backend subscribes to both legacy and new topic formats simultaneously to support ~500 Scouts across ~30 customers on old firmware during the migration period.

| Format | Topic pattern | Payload format | Backend subscription |
|--------|--------------|----------------|----------------------|
| Legacy v1 | `fm/mm/{scout_serial}/telemetry` | CSV string — 12 values: 4 relays, 4 analog inputs, 4 digital inputs | `fm/mm/+/#` |
| Legacy v1 | `fm/mm/{scout_serial}/weatherstation` | ⚑ Payload format TBC — hardware team input required | `fm/mm/+/#` |
| Legacy v1 | `fm/mm/{scout_serial}/tbox` | ⚑ Payload format TBC — hardware team input required | `fm/mm/+/#` |
| Legacy v1 | `fm/mm/{scout_serial}/abb` | ⚑ Payload format TBC — hardware team input required | `fm/mm/+/#` |
| That Place v1 | `that-place/scout/{scout_serial}/telemetry` | JSON key-value object | `that-place/scout/+/#` |
| That Place v1 | `that-place/scout/{scout_serial}/{device_serial}/telemetry` | JSON key-value object | `that-place/scout/+/#` |

**Legacy v1 telemetry CSV field mapping (confirmed):**

`fm/mm/{scout_serial}/telemetry` publishes a 12-value comma-separated string. Field order:

| Position | Stream key | Type |
|----------|-----------|------|
| 0 | `Relay_1` | boolean |
| 1 | `Relay_2` | boolean |
| 2 | `Relay_3` | boolean |
| 3 | `Relay_4` | boolean |
| 4 | `Analog_1` | numeric |
| 5 | `Analog_2` | numeric |
| 6 | `Analog_3` | numeric |
| 7 | `Analog_4` | numeric |
| 8 | `Digital_1` | boolean |
| 9 | `Digital_2` | boolean |
| 10 | `Digital_3` | boolean |
| 11 | `Digital_4` | boolean |

**Topic router — dynamic pattern matching:**
- Incoming messages matched against a registry of topic patterns — no hardcoded parsing logic
- Each registered pattern defines how to extract: scout_serial, device_serial, message_type
- Stream values extracted from payload according to format (JSON key-value for v1, CSV with fixed mapping for legacy v1 telemetry)
- New topic formats onboarded by registering a new pattern — no code changes required

**MODBUS and other bridged protocols:**
- The Scout handles all protocol translation (MODBUS, RS485, etc.) at the edge
- That Place always receives JSON key-value telemetry regardless of the underlying device protocol
- MODBUS register-to-stream-key mapping is configured on the Scout; That Place treats MODBUS devices identically to any other JSON-publishing device

**Legacy firmware tracking:**
- Device record includes `topic_format` field: `legacy_v1` / `that_place_v1`
- Auto-detected: when a message arrives from a Scout, `topic_format` is updated to match the incoming topic prefix
- When firmware is updated and the Scout begins sending on the new prefix, `topic_format` flips to `that_place_v1` automatically — no manual intervention
- That Place Admin can filter devices by `topic_format` to track fleet migration progress
- Old Scouts re-registered as new Device records in That Place v1 during tenant onboarding — operate on `legacy_v1` until firmware updated, then seamlessly transition

**Remaining hardware team input required:**
- ⚑ **Legacy weatherstation/tbox/abb payload format** — payload structure for these message types still required before their parsers can be built
- ⚑ **Legacy command format** — current command format sent to Scouts is inconsistent (strings, JSON, raw characters). Needs clarification and a defined migration path before legacy command handling can be specced

### Non-Negotiables
- All tenant data is strictly isolated — Tenant A must never see Tenant B's data
- All API endpoints require authentication except registration and login
- All raw stream data is stored forever regardless of display settings
- Stream display/activation is a view filter, not a data filter
- Device commands can only be sent by Operator or Admin roles — enforced at API level
- That Place platform admins can access all tenants; customer users cannot cross tenants
- Every field, stream, command, and integration must be configurable — nothing hardcoded

### Explicitly Excluded (MVP)
- No webhook, Slack, or Teams notification channels
- No alert escalation policies
- No downsampled or aggregated historical data (raw values only)
- No real-time WebSocket push to frontend (polling acceptable for MVP)
- No ML/AI rule conditions (future)
- No rule approval workflows
- No PDF report builder (Phase 2)
- No Runner device support (Phase 4)
- No React Native mobile app in MVP — Phase 6
- No GraphQL — REST only
- No scheduled/email data exports (on-demand CSV only for MVP)

---

## 3. Features (User Stories + Acceptance Criteria)

### Feature: Authentication & Tenant Access

**User Story:** As a user, I want to log in securely and access only the data belonging to my organisation.

**Acceptance Criteria:**
- [ ] Email/password login with JWT access + refresh tokens
- [ ] All sessions expire on logout (token blacklist)
- [ ] That Place admin accounts can switch between and access all tenants
- [ ] Customer accounts are bound to a single tenant — cross-tenant access denied

---

### Feature: Tenant Management (That Place Admin)

**User Story:** As a That Place Admin, I want to create and manage tenant accounts so that new customers can be onboarded.

**Acceptance Criteria:**
- [ ] That Place Admin can create, view, edit, and deactivate tenants
- [ ] On tenant creation, That Place Admin sends an invite to the first Tenant Admin user
- [ ] That Place Admin can access any tenant's data for support purposes
- [ ] Deactivated tenants cannot log in but their data is retained

**Onboarding Flow:**
1. That Place Admin creates Tenant record
2. That Place Admin sends invite email to first Tenant Admin
3. Tenant Admin sets password and logs in
4. Tenant Admin creates Sites
5. Tenant Admin registers Devices by serial number (status: **pending**)
6. That Place Admin receives notification and approves devices
7. Devices connect, streams are auto-discovered
8. Tenant Admin configures streams, builds dashboards, invites users, creates rules

---

### Feature: Tenant Settings

**User Story:** As a Tenant Admin, I want to configure organisation-wide settings that apply across my tenant.

**Acceptance Criteria:**
- [ ] Tenant Admin can set the tenant timezone (IANA timezone string, e.g. "Australia/Brisbane")
- [ ] Timezone is used for: schedule gate evaluation on rules, display of timestamps in the UI
- [ ] Timezone defaults to "Australia/Sydney" at tenant creation and can be changed at any time

---

### Feature: Tenant User & Role Management

**User Story:** As a Tenant Admin, I want to manage users within my organisation and control what they can access.

**Acceptance Criteria:**
- [ ] Tenant Admin can invite users by email and assign a role on invite
- [ ] Invite tokens are cryptographically random (`secrets.token_urlsafe(32)`, 256-bit entropy); only the SHA-256 hash is stored in the DB — the raw token is never persisted
- [ ] Invite tokens expire after 72 hours and are single-use — `used_at` is set atomically on first acceptance; subsequent submissions with the same token are rejected
- [ ] Three roles: Admin, Operator, View-Only
- [ ] Tenant Admin can change a user's role or remove them
- [ ] A user belongs to exactly one tenant (except That Place Admins)
- [ ] Removed users immediately lose access

**Role Permissions:**

| Action | Admin | Operator | View-Only |
|--------|-------|----------|-----------|
| Manage devices & streams | ✓ | — | — |
| Approve device provisioning | ✓ | — | — |
| Build and edit rules | ✓ | — | — |
| Manage dashboards | ✓ | ✓ | — |
| View dashboards & data | ✓ | ✓ | ✓ |
| Send device commands | ✓ | ✓ | — |
| Acknowledge/resolve alerts | ✓ | ✓ | — |
| Manage users & groups | ✓ | — | — |
| Export data (CSV) | ✓ | ✓ | — |

---

### Feature: Notification Groups

**User Story:** As a Tenant Admin, I want to create notification groups so that rules can target the right people without listing individuals every time.

**Acceptance Criteria:**
- [ ] Tenant Admin can create custom named groups (e.g. "Maintenance Team", "On-Call Operators")
- [ ] Pre-defined system groups available: "All Users", "All Admins", "All Operators"
- [ ] Tenant Admin assigns users to groups
- [ ] A user can belong to multiple groups
- [ ] Rule actions can target one or more groups and/or individual users
- [ ] Removing a user from a group takes effect immediately on future alerts

---

### Feature: Device Type Library (That Place Admin)

**User Story:** As a That Place Admin, I want to maintain a library of supported device types so customers can select from known hardware when registering devices.

**Acceptance Criteria:**
- [ ] That Place Admin can create, view, edit, and deactivate device types
- [ ] Each device type includes: name, description, connection type (MQTT/Modbus/API/etc), push vs pull flag
- [ ] That Place Admin defines commands per device type — each with name, label, param schema (key/label/type/min/max/unit/default), and ack timeout (see Feature: Device Control)
- [ ] Device types are read-only for Tenant Admins — used for selection only
- [ ] Device Type is a grouping/filter label; it does not define or constrain stream keys
- [ ] That Place Admin declares expected streams per device type including their data type (numeric/boolean/string) — this is used by the rule builder to present correct operators. Devices may report additional undeclared streams; those default to data_type = numeric until manually corrected.
- [ ] That Place Admin defines status indicator mappings per stream per device type: a list of value → colour + label entries (e.g. `"running" → green / "Running"`, `"fault" → red / "Fault"`). Used by the Status Indicator dashboard widget.

---

### Feature: Device Registration & Provisioning

**User Story:** As a Tenant Admin, I want to register a device by serial number, and have it approved before it goes live.

**Acceptance Criteria:**
- [ ] Tenant Admin registers a device with: name, serial number, site, device type
- [ ] Tenant Admin selects MQTT auth mode at registration time: **Username / Password** (port 1883, default — works with all Scout firmware) or **Client Certificate / mTLS** (port 8883 — requires Scout firmware with TLS client cert support)
- [ ] Device is created with status: **pending**
- [ ] That Place Admin receives notification of a pending device and can approve or reject it
- [ ] On approval, device status becomes **active**, MQTT credentials are automatically provisioned via the Mosquitto Dynamic Security plugin, and stored encrypted on the Device record
  - Password mode: generates a random password, creates a per-device Mosquitto client + role with ACLs restricted to that device's serial namespace
  - Certificate mode: issues a signed X.509 client certificate (RSA 2048, 2-year validity, CN = `scout-{serial}`); certificate and encrypted private key stored on Device record
- [ ] Credentials are available to Tenant Admin on the device detail page for handoff to the hardware operator
- [ ] On deactivation or rejection, credentials are automatically revoked in Mosquitto (client disabled)
- [ ] Devices can be edited (name, site) and deactivated
- [ ] Deactivated devices retain all historical data

---

### Feature: Scout Gateway & Connected Devices

**User Story:** As a Tenant Admin, I want to register dumb/local sensors that connect through a Scout, with the Scout tracked as the data bridge.

**Acceptance Criteria:**
- [ ] Devices bridged by a Scout are registered as individual Device records
- [ ] Each bridged device has a reference to the Scout device transmitting its data
- [ ] The Scout itself is also registered as a Device
- [ ] On the device detail screen, bridged devices show which Scout they are connected through
- [ ] Decommissioning a Scout flags all bridged devices as offline

---

### Feature: Stream Discovery & Configuration

**User Story:** As a Tenant Admin, I want to see what data streams each device is reporting and configure which ones appear on dashboards.

**Acceptance Criteria:**
- [ ] Streams are automatically created when a device reports a new stream key for the first time
- [ ] Each stream record includes: device, key (machine-readable), label (human-readable), unit, data type
- [ ] Tenant Admin can set a human-readable label and unit override per stream
- [ ] Tenant Admin can mark streams as display-enabled or display-disabled
- [ ] All streams store data regardless of display setting
- [ ] Unknown stream keys from unregistered serial numbers are logged and discarded

---

### Feature: Device Health Monitoring

**User Story:** As a Tenant Admin or Operator, I want to see the health status of each device so I know if hardware is offline or degraded.

**Acceptance Criteria:**
- [ ] Platform tracks per device: online/offline status, last-seen timestamp, first-active timestamp, signal strength, battery level, activity level
- [ ] Device list shows a health status indicator at a glance (colour-coded)
- [ ] **Offline threshold:** That Place Admin sets a default offline threshold per device type (e.g. "mark offline if no data for 15 minutes"). Tenant Admin can override the threshold per device instance (e.g. a critical device may have a tighter threshold)
- [ ] **Activity level** is derived by the platform from signal strength, battery level, and time since last message — not manually set. Enum: `normal / degraded / critical`. Derived rules:
  - `normal` — signal > -70 dBm (or null) AND battery > 40% (or null) AND recently heard from
  - `degraded` — signal -70 to -85 dBm OR battery 20–40% OR time since last message > 75% of offline threshold
  - `critical` — signal < -85 dBm OR battery < 20% OR just came back online after being offline
- [ ] **Activity level thresholds are configurable per tenant** via TenantSettings. Platform defaults apply if not overridden:
  - `signal_degraded_threshold`: -70 dBm (default)
  - `signal_critical_threshold`: -85 dBm (default)
  - `battery_degraded_threshold`: 40% (default)
  - `battery_critical_threshold`: 20% (default)
  - `offline_approaching_percent`: 75% of offline threshold triggers degraded (default)
- [ ] **Legacy v1 devices** have no battery or signal data — activity level derived from time since last message only. `battery_level` and `signal_strength` remain null.
- [ ] **Battery and signal stored as virtual streams** — `_battery` and `_signal` reserved keys in v1 Scout telemetry are stored as `StreamReading` records alongside regular telemetry. This makes them available to the rule engine and dashboard charts without special handling. Mains-powered Scouts always send `_battery: 100`.
- [ ] Health metrics (battery level, signal strength) are both **displayable on dashboards** and **usable as rule conditions** in the rule builder via virtual streams
- [ ] Health metrics can be added to dashboards as widgets (e.g. uptime chart, battery gauge)
- [ ] All users including View-Only can see device health
- [ ] `last_seen_at` is updated on every received message of any type (telemetry, any future message types) for both v2 and legacy v1 devices

---

### Feature: Data Ingestion — MQTT (Scout Devices)

**User Story:** As the platform, I want to receive and store data from Scout-connected devices in near real time.

**Acceptance Criteria:**
- [ ] Backend subscribes to `that-place/scout/+/#` and routes all incoming messages
- [ ] Telemetry messages are parsed and stored as StreamReadings on the correct stream
- [ ] Unknown stream keys on a known device automatically create new Stream records
- [ ] Messages from unregistered or unapproved devices are logged and discarded
- [ ] Ingestion latency from MQTT receipt to stored reading is under 5 seconds
- [ ] `DeviceHealth.last_seen_at` is updated on every received message for both v2 and legacy v1 devices
- [ ] `_battery` and `_signal` reserved keys in v1 Scout telemetry update `DeviceHealth` and are stored as virtual StreamReadings
- [ ] Scout health topic (`that-place/scout/{serial}/health`) — Phase 2 only, not implemented in MVP

---

### Feature: Data Ingestion — 3rd Party APIs

**User Story:** As a Tenant Admin, I want to connect approved 3rd-party data sources so their data appears alongside device streams.

**Design principle:** That Place Admin does all integration work once per provider. Every tenant using that provider gets an auto-generated credential form and a guided device discovery flow — no manual config required beyond entering credentials and selecting devices.

**Platform-level (That Place Admin):**
- [ ] That Place Admin creates and maintains a library of provider configs (`ThirdPartyAPIProvider`)
- [ ] Each provider config defines:
  - Identity: name, slug, description, logo (file upload — stored in S3/MinIO, not a URL)
  - Base URL
  - Auth type: `api_key_header` / `api_key_query` / `bearer_token` / `basic_auth` / `oauth2_client_credentials` / `oauth2_password` / `dual_api_key` (key as query param + secret as request header — used by e.g. Davis WeatherLink v2)
  - Auth param schema (JSONB): declares credential fields the tenant must fill in — label, type, whether secret. Used to auto-generate the credential form.
  - Discovery endpoint (JSONB): path + method + JSONPath to extract device ID from each list item + optional JSONPath for device name
  - Device detail endpoint (JSONB, optional): path template with `{device_id}` + method + `name_jsonpath`. When configured, a background Celery task calls this endpoint for each newly connected device to populate the virtual device name from the provider's own metadata. Not called during the wizard (avoids rate-limit spikes for large fleets). Leave empty for providers that already return names from discovery (SoilScout, Davis WeatherLink).
  - Detail endpoint (JSONB): path template with `{device_id}` + method + optional `params` dict (query parameters; values may contain time tokens `{from_unix}`, `{to_unix}` for Unix timestamps, or `{from_iso}`, `{to_iso}` for ISO 8601 UTC strings — interpolated from `last_polled_at` → `now` on each poll cycle) + optional `window_seconds` (int, default 300 — fallback window for the first poll when `last_polled_at` is None)
  - Available streams (JSONB array): each stream has key, label, unit, data_type, and a JSONPath expression to extract its value from the detail endpoint response
  - Default poll interval (seconds) — minimum 30 s, default 300 s (5 minutes)
  - Max requests per second (optional) — provider API rate limit; when set, poll dispatch is staggered so no more than this many device polls are sent per second
  - Commands (JSONB array, optional): control actions the provider supports. **Same schema as `DeviceType.commands`** (name, label, description, params array) with two additional fields per entry: `endpoint` (path template, may include `{device_id}`) and `method` (GET/POST/PUT/PATCH). Commands here are dispatched as authenticated HTTP calls to the provider API — not MQTT publishes. The command picker on the device detail screen shows these commands when the device is a virtual device; it shows `DeviceType.commands` for MQTT devices. Both share the same param schema and the same `CommandLog` record for history and audit.
- [ ] Provider configs are visible to Tenant Admins (name + description only) — credential schemas and JSONPath internals are not exposed
- [ ] JSONPath expressions are evaluated using `jsonpath_ng` (core module only — not `jsonpath_ng.ext`). Standard path navigation (`$.field`, `[*]`, `$.results[*].id`) is supported. Filter expressions (`?(@.price > 100)`) and arithmetic are intentionally unsupported — the parser will raise an error if a provider config contains them. This is a deliberate security constraint (SR-08).

**Tenant-level (Tenant Admin) — connection wizard:**

The connection flow is a two-phase wizard:

_Phase A — Select & assign devices_
- [ ] Tenant Admin picks a provider from the library and enters credentials (form auto-generated from provider's `auth_param_schema`)
- [ ] On credential submission, platform calls the discovery endpoint and returns the list of devices found on that account
- [ ] Tenant Admin sets a **default site** for all discovered devices (dropdown), with per-device site override per row
- [ ] When discovery returns a large result set, Tenant Admin can **search/filter the device list** by device name or external ID — filtering is client-side (no additional API call); the search input appears above the device table after discovery completes; "select all" and the selection count reflect only the currently visible (filtered) devices
- [ ] Tenant Admin selects which devices to connect via checkboxes (select-all supported)
- [ ] Virtual devices are auto-named `{ProviderName} — {external_device_name}` (editable later from device detail)

_Phase B — Configure streams_
- [ ] Tenant Admin activates/deactivates streams from the provider's available stream list — applies to all selected devices as a batch
- [ ] Default label and unit values come from the provider config; editable per stream at this step
- [ ] Individual per-device stream overrides (label, unit, display_enabled) are available after connection via the device detail Streams tab

_Post-wizard:_
- [ ] One `DataSource` record created (encrypted credentials stored)
- [ ] One virtual `Device` record created per selected device, assigned to the chosen site, with `status=active` (no approval required — provider is pre-approved by FM Admin)
- [ ] One `DataSourceDevice` record per virtual device
- [ ] Streams activated at connection time as regular `Stream` records on the virtual device

**Ongoing management:**
- [ ] Celery beat task polls the detail endpoint for each active `DataSourceDevice` on the provider's poll interval. If the endpoint has `params` configured with time tokens, query parameters are interpolated from `last_polled_at` → `now` (Unix or ISO 8601 UTC depending on the token used). On the first poll, `now - window_seconds` is used as the start time.
- [ ] Response values extracted via each active stream's JSONPath expression and stored as StreamReadings on the virtual device
- [ ] After devices are connected via the wizard, a `fetch_device_metadata` Celery task is dispatched for each new `DataSourceDevice`. If the provider has `device_detail_endpoint` configured, the task calls it per device and updates the virtual device name from the response. Respects `max_requests_per_second` between calls. No-op for providers without a device detail endpoint.
- [ ] For `oauth2_password` and `oauth2_client_credentials` auth: platform handles token refresh automatically — tenant never re-enters credentials unless they change
- [ ] On 401 (server-side token revocation), platform clears the token cache and re-authenticates up to 3 times (`MAX_AUTH_RETRIES`) before recording `AUTH_FAILURE`. Non-auth failures (network errors, 5xx) are recorded immediately with no retry. Consecutive failures incremented on `DataSourceDevice.consecutive_poll_failures`; after threshold → device health warning surfaced
- [ ] **Re-discover devices on an existing DataSource** — Tenant Admin can click "Add devices" on any connected DataSource to re-run discovery against the saved account credentials without re-entering them. The discovery result shows all devices on the account; already-connected (active) devices are shown as greyed-out and non-selectable. The user selects new devices, assigns sites, and configures streams — following the same Phase A → B flow as the initial connection wizard but skipping Step 1 (credential entry). New devices start polling immediately on completion. No backend changes required — the existing `POST /api/v1/data-sources/:id/discover/` and `POST /api/v1/data-sources/:id/devices/` endpoints support this natively.
- [ ] Removing a device **deactivates** it (`DataSourceDevice.is_active = False`, polling stops) — the virtual Device record and all StreamReadings are retained. Hard delete is available from the device detail page.
- [ ] Virtual device streams are identical `Stream` records to MQTT device streams — label, unit, and display_enabled are all configurable via the existing Streams tab after connection

**MVP scope:**
- [ ] Discovery endpoint (list devices) + detail endpoint (current/latest measurement per device) — MVP
- [ ] History endpoint (date-range polling for backfill) — Phase 2 (see Open Questions)

---

### Feature: Feed Providers (API-Polled Data Channels)

**User Story:** As a That Place Admin, I want to configure API-polled data feeds so that live external values (market prices, indices, forecasts) are available to all tenants as rule condition sources — without needing device records.

**Design principle:** The same configuration-driven approach as `ThirdPartyAPIProvider`, but feed-centric. A feed produces named scalar channels over time rather than per-device stream readings. Adding a new feed requires only a new provider record — no code changes.

**Platform-level (That Place Admin):**
- [ ] That Place Admin creates and maintains a library of `FeedProvider` configs
- [ ] Each provider config defines:
  - Identity: name, slug, description
  - Base URL
  - Auth type: `none` / `api_key_header` / `bearer_token` / `oauth2_client_credentials` / `oauth2_password`
  - Auth param schema (JSONB): credential fields required — used to auto-generate credential forms for `scope=tenant` providers
  - Scope: `system` — polled once globally, readings available to all tenants; `tenant` — each tenant subscribes with their own credentials
  - Poll interval (seconds, min 60, default 300)
  - Endpoints (JSONB array): each endpoint has `path`, `method`, optional `response_root_jsonpath` (JSONPath to iterate rows — omit for single-object responses), optional `dimension_key` (field in each row that identifies the channel variant, e.g. `"REGIONID"`), and `channels` (array of `key`, `label`, `unit`, `data_type`, `value_jsonpath`)
- [ ] On provider create/update, `FeedChannel` records are auto-populated from the endpoint channel config — one record per channel × dimension value combination. Dimension values are discovered on the first successful poll and are not pre-configured.
- [ ] Provider configs visible to Tenant Admins (name + description only) — auth schemas and JSONPath internals not exposed
- [ ] JSONPath expressions are evaluated using `jsonpath_ng` (core module only — not `jsonpath_ng.ext`). Standard path navigation is supported; filter expressions and arithmetic are not (SR-08).

**System-scope feed polling:**
- [ ] Celery beat task polls each active `scope=system` provider on its configured interval
- [ ] For each endpoint: fetches URL, iterates `response_root_jsonpath` (or treats response as single object), extracts dimension value and channel values via JSONPath, stores `FeedReading` records
- [ ] `unique_together: (channel_id, timestamp)` — duplicate readings are silently ignored (idempotent)
- [ ] On new `FeedReading`, a Celery task dispatches rule evaluation for all rules referencing that channel (via `FeedChannelRuleIndex`) — same pattern as `RuleStreamIndex` for stream readings
- [ ] Poll failures are logged; after 3 consecutive failures a platform notification is sent to That Place Admins

**Tenant-scope feeds:**
- [ ] Tenant Admin subscribes to a `scope=tenant` provider via a connection flow (enter credentials → channels auto-listed → select which to subscribe)
- [ ] `TenantFeedSubscription` record stores encrypted credentials and subscribed channel IDs
- [ ] Celery beat task polls each active subscription on the provider's interval
- [ ] Readings stored as `FeedReading` records on the shared `FeedChannel` — readings are NOT tenant-isolated at the model level for system feeds; for tenant-scope feeds, readings are stored against tenant-specific channel instances

**AEMO NEM — first registered system feed:**
- [ ] AEMO NEM registered as a `scope=system` provider on first deployment (see `docs/providers/aemo-nem.md`)
- [ ] Channels: `rrp` (spot price $/MWh), `raise_reg_rrp`, `lower_reg_rrp`, and full FCAS band prices — per region (NSW1, QLD1, SA1, TAS1, VIC1)
- [ ] No auth required; poll interval 300 seconds

---

### Feature: Reference Datasets (Admin-Managed Lookup Tables)

**User Story:** As a That Place Admin, I want to define structured lookup tables of reference data (network tariff rates, CO2 emission factors, fuel price indices) so that tenants can assign them to sites and use the values in rule conditions and cost calculations — without needing code changes to add a new dataset type.

**Design principle:** A generic "lookup table builder". The admin defines the schema (columns) of a dataset once; rows are managed via the admin UI. Datasets can optionally support time-of-use (rows apply only during certain hours/days) and versioning (rows are labelled by period, e.g. financial year). Tenants are assigned to specific row subsets via dimension filters.

**Platform-level (That Place Admin):**
- [ ] That Place Admin creates and maintains `ReferenceDataset` configs defining:
  - Identity: name, slug, description
  - Dimension schema (JSONB array): `[{key, label, type}]` — the lookup key columns used to identify which rows apply (e.g. `distributor_slug`, `tariff_code`, `energy_source`)
  - Value schema (JSONB array): `[{key, label, type, unit}]` — the actual values stored in each row (e.g. `rate_cents_per_kwh`, `kg_per_kwh`)
  - `has_time_of_use` (bool): if true, rows carry `applicable_days` (int array) + `time_from` / `time_to` (time fields) — resolved in tenant timezone
  - `has_version` (bool): if true, rows carry a `version` label (e.g. `"2025-26"`) — used for annual datasets like network tariffs
  - Scope: `system` (shared, managed by That Place Admin) / `tenant` (each tenant manages their own rows — for future use)
- [ ] That Place Admin manages `ReferenceDatasetRow` records per dataset:
  - `version` (nullable string — required when `has_version` is true)
  - `dimensions` (JSONB) — values matching the dataset's dimension schema (e.g. `{distributor_slug: "ausgrid", tariff_code: "RES_TOU", period_name: "peak"}`)
  - `values` (JSONB) — actual values matching value schema (e.g. `{rate_cents_per_kwh: 32.5, daily_supply_cents: 110.0}`)
  - `applicable_days` (int array, nullable — 0=Mon…6=Sun), `time_from` (time, nullable), `time_to` (time, nullable) — only when `has_time_of_use` is true
  - `valid_from` (date, nullable), `valid_to` (date, nullable) — for date-bounded validity independent of versioning

**Tenant-level (Tenant Admin):**
- [ ] Tenant Admin creates `TenantDatasetAssignment` records per site (or tenant-wide if `site_id` is null):
  - Selects a dataset and enters `dimension_filter` (JSONB) — the dimension values that identify the correct rows for this site (e.g. `{distributor_slug: "ausgrid", tariff_code: "RES_TOU"}`)
  - Optionally pins a `version` (e.g. `"2025-26"`) — when null, always uses the latest active version
  - Sets `effective_from` / `effective_to` date range
- [ ] At evaluation time the platform resolves the applicable row(s): filter by assignment's `dimension_filter` → filter by version (pinned or latest) → if `has_time_of_use`, filter by current day/time in tenant timezone → return matching row's `values`

**Worked example — network tariffs as a ReferenceDataset:**

The `network-tariffs` dataset demonstrates how a complex, annually-updated, time-of-use rate structure is expressed entirely as data with no bespoke code:

Dataset config:
```
slug:               network-tariffs
has_version:        true    ← rows labelled by financial year ("2025-26", "2026-27")
has_time_of_use:    true    ← rows carry applicable_days + time_from/time_to
dimension_schema:   [{key: "distributor_slug"}, {key: "tariff_code"}, {key: "period_name"}]
value_schema:       [{key: "rate_cents_per_kwh", unit: "c/kWh"}, {key: "daily_supply_cents", unit: "c/day"}]
```

Sample rows (each row = one rate for one period of one tariff):

| version | dimensions | values | applicable_days | time_from | time_to |
|---------|-----------|--------|-----------------|-----------|---------|
| 2025-26 | `{distributor_slug: "ausgrid", tariff_code: "EA305", period_name: "peak"}` | `{rate_cents_per_kwh: 32.50, daily_supply_cents: 110.0}` | [0,1,2,3,4] | 07:00 | 21:00 |
| 2025-26 | `{distributor_slug: "ausgrid", tariff_code: "EA305", period_name: "off_peak"}` | `{rate_cents_per_kwh: 12.80, daily_supply_cents: 110.0}` | [0,1,2,3,4,5,6] | 21:00 | 07:00 |
| 2025-26 | `{distributor_slug: "energex", tariff_code: "CAC", period_name: "flat"}` | `{rate_cents_per_kwh: 28.10, daily_supply_cents: 95.0}` | null | null | null |

Tenant assignment (Tenant Admin sets this per site):
```
dataset:          network-tariffs
dimension_filter: {distributor_slug: "ausgrid", tariff_code: "EA305"}
version:          null   ← always use latest active version
effective_from:   2025-07-01
```

Resolution at rule evaluation time:
1. Find site's active `TenantDatasetAssignment` for `network-tariffs` → dimension filter `{distributor_slug: "ausgrid", tariff_code: "EA305"}`
2. Query rows matching those dimensions + latest version (`2025-26`)
3. `has_time_of_use` is true → filter by current day/time in tenant timezone → selects "peak" or "off_peak" row
4. Return `rate_cents_per_kwh` → evaluate condition

**What "dynamic" means — what requires code vs. what does not:**

| Task | How it's done | Code changes required? |
|------|--------------|------------------------|
| Add a new DNSP | Add rows with a new `distributor_slug` | No |
| Add a new tariff type for an existing DNSP | Add rows with a new `tariff_code` | No |
| Update rates each July 1 | Add rows with `version: "2026-27"`; old rows retained for history | No |
| Add a new dataset type (e.g. water rates, gas prices) | Create a new `ReferenceDataset` with its own dimension + value schema | No |
| Add TOU complexity to a currently flat tariff | Add `applicable_days`/`time_from`/`time_to` to the new version's rows | No |
| Tenant changes DNSP or tariff type | Tenant Admin updates their `TenantDatasetAssignment` dimension filter | No |
| Define an entirely new schema structure | Create a new `ReferenceDataset` with any combination of dimension/value columns | No |
| Change the resolution logic (e.g. new version selection rule) | Code change to row resolver | Yes — this is the only case |

The schema is defined once by That Place Admin through the admin UI. All subsequent data management — new DNSPs, new tariff products, annual rate updates, new dataset categories — is pure data entry.

**Seeded datasets on first deployment:**
- [ ] `network-tariffs` — network tariff rates for all 8 Australian NEM DNSPs; dimension schema: `distributor_slug`, `tariff_code`, `period_name`; value schema: `rate_cents_per_kwh`, `daily_supply_cents`; `has_time_of_use: true`, `has_version: true`
- [ ] `co2-emission-factors` — kg CO2 equivalent per kWh by energy source; dimension schema: `energy_source`; value schema: `kg_per_kwh`; `has_time_of_use: false`, `has_version: false`

**Rule integration:**
- [ ] New rule condition type `reference_value`: Tenant Admin selects a dataset, optionally overrides dimension filter, selects a value key, and sets operator + threshold
- [ ] `reference_value` conditions are evaluated on a Celery beat schedule (every 5 minutes) for rules where the only condition source is reference data — catches time-of-use boundary changes without requiring an incoming reading to trigger evaluation
- [ ] `reference_value` conditions are also evaluated inline whenever another condition in the same rule triggers evaluation (a new stream reading or feed reading)

---

### Feature: Dashboards & Visualisation

**User Story:** As any tenant user, I want configurable dashboards showing live and historical data from my devices.

**Acceptance Criteria:**

**Dashboard management:**
- [ ] Tenant Admin and Operator can create, edit, and delete dashboards
- [ ] Dashboards are shared across the whole tenant — all users see the same dashboards
- [ ] Dashboards are visible to all users including View-Only (read-only for them)
- [ ] Tenant Admin and Operator can edit an existing widget's configuration (stream binding, label, thresholds, time range, etc.) without deleting and recreating it — the widget builder modal re-opens pre-populated with the current config and saves via the existing PUT endpoint
- [ ] Per-user personal dashboards — Phase 2

**Layout:**
- [ ] Fixed grid layout — Tenant Admin selects number of columns per dashboard (1, 2, or 3)
- [ ] Widgets are ordered within the grid; order is drag-to-reorder within the column structure
- [ ] On tablet-width browsers (768–1024px), widgets reflow to a single column automatically

**Widget types:**
- [ ] **Line chart** — plots one or more streams over time; each stream rendered as a separate line; configurable time range (last hour / 24h / 7d / 30d / custom with plain date inputs). Dual Y-axis: all streams default to the left axis; any stream beyond the first can be individually toggled to the right axis. Implemented with ApexCharts.
- [ ] **Gauge** — displays current value of a single stream against a min/max range; configurable min, max, and exactly 3 fixed threshold bands (normal / warning / danger) with configurable boundary values (`warning_threshold`, `danger_threshold`); band colours are green / yellow / red using semantic tokens. Implemented with ApexCharts.
- [ ] **Value card** — displays latest reading for a single stream, a trend indicator (up / down / stable, derived from comparison to previous reading), and time since last update
- [ ] **Status indicator** — displays a colour/label state derived from a stream's current value; state-to-colour/label mapping defined at device type configuration by That Place Admin
- [ ] **Health/uptime chart** — plots a device's online/offline history over time, or battery/signal as a line chart

**General:**
- [ ] Each widget bound to one or more streams or health metrics
- [ ] Cross-site widgets: a single widget can include streams from multiple devices across multiple sites
- [ ] Live data refreshes automatically on a configurable polling interval (default: 30 seconds)
- [ ] Widget config stored as JSONB — supports flexible per-widget settings without schema changes

**Widget titles:**
- [ ] Every widget has an editable title stored in the config JSONB as `"title"`
- [ ] Default title is auto-generated from the device names bound to the widget: if one device → `"<Device Name>"`; if two devices → `"<Device A> & <Device B>"`; if three or more → `"<Device A>, <Device B> + N more"`. This default is computed on the frontend at widget-creation time and saved into the config — it is not recomputed dynamically after save.
- [ ] The title is displayed at the top of every widget card on the dashboard
- [ ] Tenant Admin and Operator can edit the title inline on the widget card (single click opens an editable text input; blur or Enter saves via the existing PUT endpoint)
- [ ] Title is always shown in the widget builder modal as an editable field, pre-populated with the current value (or the auto-generated default for new widgets)
- [ ] Title is a free-text string; maximum 120 characters; may not be blank

**Widget config schemas (JSONB):**

`value_card`:
```json
{
  "title": "Tank Level — Site A",
  "stream_id": 123,
  "label_override": "Tank Level"
}
```

`line_chart`:
```json
{
  "title": "Sensor A & Sensor B",
  "streams": [
    { "stream_id": 123, "axis": "left", "color": "#hex" },
    { "stream_id": 456, "axis": "right", "color": "#hex" }
  ],
  "time_range": "24h"
}
```
`time_range` values: `"1h"` / `"24h"` / `"7d"` / `"30d"` / `"custom"`. When `"custom"`, two additional fields are present: `"date_from": "YYYY-MM-DD"` and `"date_to": "YYYY-MM-DD"`.

`gauge`:
```json
{
  "title": "Pressure — Pump House",
  "stream_id": 123,
  "min": 0,
  "max": 100,
  "warning_threshold": 60,
  "danger_threshold": 80,
  "label_override": "Pressure"
}
```
Values below `warning_threshold` = normal (green); between `warning_threshold` and `danger_threshold` = warning (yellow); above `danger_threshold` = danger (red).

---

### Feature: Rules Engine

**User Story:** As a Tenant Admin, I want to build automation rules using a visual interface so the system acts automatically when conditions are met.

**Acceptance Criteria:**

**Rule structure:**
- [ ] Visual rule builder — no code required
- [ ] Step flow: name/description → schedule gate → conditions → actions → review & save
- [ ] Rules have: name, description, active/inactive toggle, optional cooldown, optional schedule gate, one or more condition groups, one or more actions

**Re-triggering model:**
- [ ] A rule fires when its combined condition transitions from false → true
- [ ] While the condition remains true, the rule is suppressed — it does not re-fire on every reading
- [ ] Optional cooldown per rule: minimum number of minutes between firings, even after the condition clears
- [ ] Every stream referenced in any condition of a rule triggers full re-evaluation of that rule (not just a primary stream)

**Schedule gate (optional):**
- [ ] Each rule has an optional schedule gate — if set, the rule is only evaluated during the gated window
- [ ] Gate config: multi-select days (Mon/Tue/Wed/Thu/Fri/Sat/Sun, with shortcuts: Weekdays / Weekends / Every day) plus an optional time window (from / to)
- [ ] Schedule gate evaluated in the tenant's configured timezone
- [ ] If no gate is set, the rule evaluates at all times

**Conditions:**
- [ ] Conditions are organised into groups — one level of nesting maximum
- [ ] Each group has its own AND/OR operator applied across its conditions
- [ ] Groups are combined at the rule level with a single top-level AND/OR operator
- [ ] Conditions can reference any stream from any device within the tenant
- [ ] Stream picker UI: site → device → stream (hierarchical drill-down)
- [ ] Condition operators are gated by stream data type:
  - Numeric streams: `>`, `<`, `>=`, `<=`, `==`, `!=`
  - Boolean streams: `== true`, `== false`
  - String/Enum streams: `==`, `!=`
- [ ] Staleness conditions: "stream has not reported in X minutes/hours" — available as a condition type for any stream
- [ ] Staleness conditions are evaluated by a Celery beat scheduled task, not ingestion-triggered
- [ ] Feed channel conditions: reference a `FeedChannel` (provider → channel → optional dimension value, e.g. NSW1 spot price); numeric operators only; evaluated against the latest `FeedReading` for that channel; triggers rule evaluation via `FeedChannelRuleIndex` when a new reading arrives
- [ ] Reference value conditions: reference a `ReferenceDataset` value key (resolved via the site's `TenantDatasetAssignment` at evaluation time, including TOU period lookup in tenant timezone); numeric operators only; evaluated on a Celery beat schedule (every 5 minutes) and also inline when another condition in the same rule is triggered

**Actions:**
- [ ] Rule actions: send notification to groups/users AND/OR send device command
- [ ] Notification action: select channels (in-app / email / SMS / push), select target groups and/or individual users, write message template
- [ ] Message template supports variable interpolation: `{{device_name}}`, `{{stream_name}}`, `{{value}}`, `{{unit}}`, `{{triggered_at}}`, `{{rule_name}}`, `{{site_name}}`
- [ ] Device command action: select target device and command (from device type's registered commands)
- [ ] Rules can be enabled/disabled without deleting

---

### Feature: Rule Versioning & Audit Trail

**User Story:** As a Tenant Admin, I want to see a change history on each rule.

**Acceptance Criteria:**
- [ ] Every save creates an audit log entry: changed by, timestamp, fields changed (before/after values)
- [ ] Audit history visible on rule detail screen
- [ ] Audit log is append-only — cannot be edited or deleted

---

### Feature: Alerts

**User Story:** As a Tenant Admin or Operator, I want to see a feed of triggered alerts and manage their status.

**Acceptance Criteria:**
- [ ] Each rule firing creates an Alert record
- [ ] Alert states: active → acknowledged → resolved (one-directional)
- [ ] Admin and Operator can acknowledge or resolve alerts — View-Only users see the feed read-only
- [ ] Acknowledging an alert requires a single tap; an optional free-text "Troubleshooting explanation" field is shown on the acknowledge action
- [ ] Alert feed uses an **active alert model**: active alerts are the primary view — what is wrong right now
- [ ] Separate alert history view showing all past firings — filterable by site, device, rule, and status
- [ ] Each alert card shows: rule name, triggered at, status badge, site, device

---

### Feature: Notifications

**User Story:** As a user, I want to receive notifications through my preferred channels when alerts fire or significant system events occur.

**Acceptance Criteria:**

**Channels:**
- [ ] Supported channels: in-app, email, SMS, mobile push
- [ ] Rule actions specify which channels to use and which groups/users to target
- [ ] Channel defaults: in-app and email are **on by default**; SMS is **off by default** and must be explicitly opted into by each user
- [ ] Each user manages their channel preferences individually — opt out of email/in-app, opt in to SMS
- [ ] SMS will not be sent to a user who has not opted in, regardless of what the rule action specifies
- [ ] Per-channel opt-out/opt-in per rule — Phase 2

**Alert-triggered notifications:**
- [ ] When a rule fires, notifications are sent via the channels and targets defined in the rule action
- [ ] In-app notification badge shows unread count
- [ ] Tapping a notification marks it as read and navigates to the related alert
- [ ] "Mark all as read" button marks every unread notification for the user as read in a single action
- [ ] Tapping a push notification deep-links directly to the alert detail screen
- [ ] App closed: notification delivered as OS banner / lock screen notification
- [ ] App open: notification delivered as an in-app banner/toast
- [ ] Email and SMS delivery failures are logged and retried once

**Notification snooze:**
- [ ] A user can snooze notifications for a specific rule for a configurable duration: 15 min, 1 hour, 4 hours, or 24 hours
- [ ] While a snooze is active, the user does not receive any new notifications (in-app, email, SMS, push) when that rule fires — existing unread notifications are not affected
- [ ] Snooze is per-user and per-rule — other users are not affected
- [ ] Snooze expires automatically at the chosen time — no manual cancellation required, but a "Cancel snooze" option is provided
- [ ] Snoozed rules are visually indicated in the notification panel (e.g. a clock icon with the expiry time)
- [ ] Snooze is enforced at notification creation time — if the user has an active snooze for the rule, no notification row is written for that user

**System event notifications:**
- [ ] The following platform events trigger in-app (and optionally email) notifications to relevant tenant users:
  - Device approved by That Place Admin
  - Device went offline (per device's configured offline threshold)
  - Device deleted
  - DataSource poll failed (after retry exhausted)
  - 3rd party API auth failure
- [ ] ⚑ **This event list is dynamic** — new system event types will be added as features are built. Each event type should be registered in a central notification event registry rather than hardcoded. Flag for architectural review during implementation.
- [ ] Notification retention: kept forever (consistent with raw data retention policy)
- [ ] ⚑ **Flag:** notification volume at scale could become a concern — revisit retention policy if needed

**That Place Admin notification channel:**
- [ ] That Place Admins have a separate system-level notification channel for platform-wide events:
  - Platform/service degradation or downtime
  - MQTT broker connectivity failures
  - 3rd party API provider failures (affecting multiple tenants)
  - Any tenant device pending approval
- [ ] ⚑ **That Place Admin notification channel design** — delivery mechanism (in-app, email, PagerDuty-style alerting) and the full event list to be defined in a dedicated deep dive

---

### Feature: Device Control

**User Story:** As a Tenant Admin or Operator, I want to send commands to a device manually or via a rule.

**Acceptance Criteria:**

**Command definition (That Place Admin):**
- [ ] Commands are defined per device type in the That Place Admin library
- [ ] Each command has: name (machine key), label (human-readable), description, and a param schema
- [ ] Param schema is a JSONB array — each param has: key, label, type (int/float/string/bool), optional min/max/unit, and an optional default value
- [ ] Params with a default value are pre-filled in the UI; params without one require the user to enter a value before sending
- [ ] Ack timeout is configured per device type (e.g. "expect ack within 30 seconds")
- [ ] Example command definition:
  ```json
  {
    "name": "set_fan_speed",
    "label": "Set Fan Speed",
    "params": [
      { "key": "speed", "label": "Speed", "type": "int", "min": 0, "max": 100, "unit": "%" }
    ]
  }
  ```

**Sending commands (Tenant Admin / Operator):**
- [ ] Admin and Operator can send a command from the device detail screen
- [ ] UI renders a form from the command's param schema — pre-filled defaults where defined, input fields for variable params
- [ ] Commands sent via MQTT: `that-place/scout/{scout_serial}/{device_serial}/cmd/{command_name}` with params as JSON payload
- [ ] View-Only users cannot send commands

**Acknowledgement:**
- [ ] Device (via Scout) publishes acknowledgement to `.../cmd/ack` — confirms receipt only (MVP)
- [ ] If no ack received within the device type's configured timeout: command log status set to `timed_out`
- [ ] ⚑ **Success/failure status in ack payload** — Phase 2. Currently Scout hardware capability to confirm execution success/failure is unknown. When confirmed, ack payload should include status (ok/error) and optional reason.

**Command history:**
- [ ] Every command is logged: sent by, timestamp, command name, params sent, ack status (sent / acknowledged / timed_out)
- [ ] Command history visible on device detail screen (Admin and Operator)

**Rule-triggered commands:**
- [ ] Rule actions can trigger device commands automatically
- [ ] Rule-triggered commands follow the same re-triggering model as the rule itself — the command fires once on the false→true condition transition and is suppressed while the rule remains in a triggered state. No additional guardrails required beyond the existing rule re-triggering suppression.

---

### Feature: Data Export (CSV)

**User Story:** As a Tenant Admin or Operator, I want to export raw stream data for offline analysis.

**Acceptance Criteria:**

**Export configuration:**
- [ ] User selects: date window (from / to), one or more streams (cross-device selection supported), and confirms field set
- [ ] Export is on-demand only — no scheduled or recurring exports in MVP

**Output format:**
- [ ] Single CSV file regardless of how many streams are selected
- [ ] One row per timestamp. Where multiple streams from the same device report at the same timestamp, they appear in the same row as additional column pairs
- [ ] Fixed columns: `timestamp`, `site_name`, `device_name`, `device_id`, `stream_label`
- [ ] Per selected stream: `value`, `unit` column pair (e.g. `Temperature (°C)` header with value column alongside)
- [ ] Where a stream has no reading at a given timestamp, the cell is left empty

**Delivery:**
- [ ] Export is downloaded immediately — no S3 storage, no async task, no download link
- [ ] Delivered as a Django `StreamingHttpResponse` — rows streamed to client as generated, avoids timeout on large datasets
- [ ] No file retention — export is generated fresh on every request

**Export history (Admin only):**
- [ ] Each export is logged: exported by, exported at, stream IDs exported, date range
- [ ] Export history visible to Admin only
- [ ] No download link — re-export by repeating the same configuration

---

## 4. Data Model

### Entities & Relationships

| Entity | Relationships | Key Fields |
|--------|--------------|------------|
| User | base auth | id, email, password, is_that_place_admin, created_at |
| Tenant | has many Sites, TenantUsers | id, name, slug, timezone (IANA tz string, e.g. "Australia/Brisbane"), is_active, signal_degraded_threshold (int dBm, default -70), signal_critical_threshold (int dBm, default -85), battery_degraded_threshold (int %, default 40), battery_critical_threshold (int %, default 20), offline_approaching_percent (int %, default 75), created_at |
| TenantUser | links User ↔ Tenant | id, user_id, tenant_id, role (admin/operator/viewer), joined_at |
| TenantInvite | belongs to Tenant | id, tenant_id, email, role (admin/operator/viewer), token_hash (SHA-256 hex of raw token — raw token never stored), created_by (FK → User, nullable), expires_at (72 hours from creation), used_at (nullable — set on acceptance; null = not yet used), created_at |
| Site | belongs to Tenant | id, tenant_id, name, description, latitude, longitude, created_at |
| DeviceType | platform library | id, name, slug, description, connection_type, is_push, default_offline_threshold_minutes (int), command_ack_timeout_seconds (int), commands (JSONB array — each entry: name, label, description, params array), is_active, created_at |
| Device | belongs to Site + Tenant | id, tenant_id, site_id, device_type_id, name, serial_number, gateway_device_id (nullable FK → Device), status (pending/active/deactivated), offline_threshold_override_minutes (nullable int — if set, overrides device type default), topic_format (legacy_v1/that_place_v1 — auto-detected from incoming MQTT traffic), mqtt_auth_mode (password/certificate — selected at registration; determines credential type provisioned on approval), mqtt_password (encrypted text, nullable — provisioned on approval for password mode), mqtt_certificate (text, nullable — PEM client cert for certificate mode), mqtt_private_key (encrypted text, nullable — PEM private key for certificate mode; cleared after operator confirms loading), created_at |
| DeviceHealth | one-to-one with Device | id, device_id, is_online, last_seen_at, first_active_at, signal_strength, battery_level, activity_level, updated_at |
| Stream | belongs to Device | id, device_id, key, label, unit, data_type (numeric/boolean/string — declared at device type registration, inherited by all stream instances of that type), display_enabled, created_at |
| StreamReading | belongs to Stream | id, stream_id, value (JSONB), timestamp, ingested_at |
| ThirdPartyAPIProvider | platform library | id, name, slug, description, logo (file — stored in S3/MinIO), base_url, auth_type (api_key_header/api_key_query/bearer_token/basic_auth/oauth2_client_credentials/oauth2_password/**dual_api_key**), auth_param_schema (JSONB — credential fields tenant must supply), discovery_endpoint (JSONB: path, method, device_id_jsonpath, device_name_jsonpath), **device_detail_endpoint** (JSONB optional: path_template with {device_id}, method, name_jsonpath — called as background task after connect to populate virtual device names; leave empty when discovery already returns names), detail_endpoint (JSONB: path_template with {device_id}, method, **params** (optional dict — values may contain time tokens {from_unix}/{to_unix} for Unix timestamps or {from_iso}/{to_iso} for ISO 8601 UTC; interpolated from last_polled_at→now on each poll), **window_seconds** (int default 300 — fallback time window for first poll when last_polled_at is None)), available_streams (JSONB array: key/label/unit/data_type/jsonpath), **commands** (JSONB array, nullable — same schema as DeviceType.commands {name, label, description, params} plus {endpoint, method} per entry; dispatched as authenticated HTTP calls, not MQTT; null means the provider has no control actions), default_poll_interval_seconds (min 30, default 300), max_requests_per_second (nullable int — provider API rate limit; when set, poll dispatch is staggered so no more than this many device polls fire per second), is_active, created_at |
| DataSource | belongs to Tenant | id, tenant_id, provider_id (FK → ThirdPartyAPIProvider), name, credentials (encrypted JSONB — filled from provider's auth_param_schema), auth_token_cache (encrypted JSONB — stores access/refresh tokens for oauth2 types), is_active, created_at |
| DataSourceDevice | belongs to DataSource | id, datasource_id, external_device_id (device ID as returned by provider's discovery endpoint), external_device_name (nullable), virtual_device_id (FK → Device), active_stream_keys (array — subset of provider's available_streams the tenant has activated), **poll_interval_seconds** (nullable int, min 30 — overrides provider default when set; null means use provider default), last_polled_at, last_poll_status (ok/error/auth_failure), last_poll_error (nullable text), consecutive_poll_failures (int, default 0), is_active |
| NotificationGroup | belongs to Tenant | id, tenant_id, name, is_system (bool — for pre-defined groups), created_at |
| NotificationGroupMember | links TenantUser ↔ NotificationGroup | id, group_id, tenant_user_id, added_at |
| Rule | belongs to Tenant | id, tenant_id, name, description, is_active, cooldown_minutes (nullable int), active_days (int array, nullable — 0=Mon…6=Sun), active_from (time, nullable), active_to (time, nullable), condition_group_operator (AND/OR), current_state (bool — tracks last evaluated result for re-trigger suppression), last_fired_at (nullable datetime), created_by, created_at, updated_at |
| RuleStreamIndex | links Stream ↔ Rule | id, stream_id, rule_id — auto-maintained index for efficient rule lookup on ingestion |
| RuleConditionGroup | belongs to Rule | id, rule_id, logical_operator (AND/OR), order |
| RuleCondition | belongs to RuleConditionGroup | id, group_id, condition_type (stream/staleness/feed_channel/reference_value), stream_id (FK → Stream, nullable), operator (nullable — operators vary by stream data_type), threshold_value (nullable text), staleness_minutes (nullable int), channel_id (FK → FeedChannel, nullable — for feed_channel type), dataset_id (FK → ReferenceDataset, nullable — for reference_value type), value_key (nullable string — which value_schema field to compare, for reference_value type), dimension_overrides (nullable JSONB — overrides TenantDatasetAssignment dimension_filter for this condition, for reference_value type), order |
| RuleAction | belongs to Rule | id, rule_id, action_type (notify/command), notification_channels (array: in_app/email/sms/push), group_ids (array), user_ids (array), message_template, target_device_id (nullable), command (nullable) |
| RuleAuditLog | belongs to Rule | id, rule_id, changed_by, changed_at, changed_fields (JSONB: {field: {before, after}}) |
| Alert | belongs to Rule + Tenant | id, rule_id, tenant_id, triggered_at, status (active/acknowledged/resolved), acknowledged_by, acknowledged_at, acknowledged_note (nullable text), resolved_by, resolved_at |
| Notification | belongs to User | id, user_id, notification_type (alert/system_event), alert_id (nullable FK → Alert — set for alert-triggered notifications), event_type (nullable — e.g. device_offline/device_approved/datasource_failure/device_deleted), event_data (nullable JSONB — context for the event), channel (in_app/email/sms/push), sent_at, read_at, delivery_status (sent/delivered/failed) |
| UserNotificationPreference | one-to-one with User | id, user_id, in_app_enabled (bool, default true), email_enabled (bool, default true), sms_enabled (bool, default false), phone_number (text, blank — E.164 format; required for SMS delivery) — created on first GET with defaults; get_or_create always used |
| NotificationSnooze | belongs to User | id, user_id, rule_id (FK → Rule), snoozed_until (datetime), created_at — unique_together: (user_id, rule_id); enforced at notification creation time to prevent writing notifications during the snooze window |
| CommandLog | belongs to Device | id, device_id, sent_by (nullable FK → User — null if rule-triggered), triggered_by_rule_id (nullable FK → Rule), command_name, params_sent (JSONB), sent_at, ack_received_at (nullable), status (sent/acknowledged/timed_out) |
| DataExport | belongs to Tenant + User | id, tenant_id, exported_by, stream_ids (array), date_from, date_to, exported_at |
| Dashboard | belongs to Tenant | id, tenant_id, name, created_by, created_at |
| DashboardWidget | belongs to Dashboard | id, dashboard_id, widget_type, config (JSONB — includes stream binding; see widget config schemas in Dashboards feature), position (JSONB) |
| FeedProvider | platform library | id, name, slug, description, base_url, auth_type (none/api_key_header/bearer_token/oauth2_client_credentials/oauth2_password), auth_param_schema (JSONB — credential fields for scope=tenant providers), scope (system/tenant), poll_interval_seconds (min 60, default 300), endpoints (JSONB array: path, method, response_root_jsonpath, dimension_key, channels[key/label/unit/data_type/value_jsonpath]), is_active, created_at |
| FeedChannel | belongs to FeedProvider | id, provider_id, key, label, unit, data_type (numeric/boolean/string), dimension_value (nullable string — e.g. "NSW1"; null for dimensionless channels), is_active |
| FeedReading | belongs to FeedChannel | id, channel_id, value (JSONB), timestamp, fetched_at — unique_together: (channel_id, timestamp) |
| TenantFeedSubscription | belongs to Tenant + FeedProvider | id, tenant_id, provider_id, credentials (encrypted JSONB — for scope=tenant providers only), subscribed_channel_ids (int array), is_active, last_polled_at, last_poll_status (ok/error/auth_failure), last_poll_error (nullable text) |
| FeedChannelRuleIndex | links FeedChannel ↔ Rule | id, channel_id, rule_id — auto-maintained on rule create/edit/delete; same pattern as RuleStreamIndex |
| ReferenceDataset | platform library | id, name, slug, description, dimension_schema (JSONB array: [{key, label, type}] — lookup key columns), value_schema (JSONB array: [{key, label, type, unit}] — value columns), has_time_of_use (bool), has_version (bool), scope (system/tenant), is_active, created_at |
| ReferenceDatasetRow | belongs to ReferenceDataset | id, dataset_id, version (nullable string — e.g. "2025-26"; required when dataset.has_version is true), dimensions (JSONB — values matching dimension_schema), values (JSONB — values matching value_schema), applicable_days (int array, nullable — 0=Mon…6=Sun), time_from (time, nullable), time_to (time, nullable), valid_from (date, nullable), valid_to (date, nullable), is_active |
| TenantDatasetAssignment | belongs to Tenant + Site (optional) + ReferenceDataset | id, tenant_id, site_id (nullable — null = tenant-wide), dataset_id, dimension_filter (JSONB — identifies applicable rows for this tenant/site, e.g. {distributor_slug: "ausgrid", tariff_code: "RES_TOU"}), version (nullable string — pinned version; null = always use latest active), effective_from (date), effective_to (date, nullable), created_at |

### Key Business Rules
- Every queryset must be filtered by `tenant_id` — no cross-tenant data leakage
- A User belongs to at most one Tenant (That Place Admins belong to none but access all)
- Streams are created automatically on first data receipt — never pre-defined
- All StreamReadings are retained forever — no deletion policy
- A Device's `tenant_id` is set directly (not just via Site) to support cross-site queries
- `gateway_device_id` on Device is nullable — only set for Scout-bridged devices
- Device status must be `active` before StreamReadings are accepted
- RuleAuditLog entries are immutable — no update or delete
- Alert status transitions are one-directional: active → acknowledged → resolved
- Rule.current_state is updated on every evaluation — it is the authoritative record of whether a rule is currently in a triggered state, used to suppress re-firing
- Rule.last_fired_at is used in conjunction with cooldown_minutes to determine whether a rule is allowed to fire again
- RuleCondition.operator valid values are constrained by the referenced stream's data_type: numeric (>, <, >=, <=, ==, !=), boolean (==), string (==, !=)
- Schedule gate (active_days / active_from / active_to) is evaluated in the tenant's timezone — all times stored as wall-clock time, not UTC
- A RuleCondition with condition_type = staleness does not use operator or threshold_value — only staleness_minutes
- Pre-defined NotificationGroups (All Users, All Admins, All Operators) are maintained automatically by the system — membership derived from TenantUser roles, not manually managed
- DataSource credentials must be stored encrypted
- Virtual devices (created from 3rd-party API connection) are created with `status=active` — no That Place Admin approval required (the provider itself is pre-approved)
- Virtual device `serial_number` is generated as `api-{provider_slug}-{tenant_id}-{external_device_id}` — guaranteed unique across all tenants
- Removing a device from a DataSource deactivates it (`DataSourceDevice.is_active=False`) — the virtual Device record and all StreamReadings are retained; hard delete is available from the device detail page
- Re-connecting a previously deactivated device reactivates the existing virtual Device and DataSourceDevice records rather than creating duplicates — poll failure counters are reset, historical StreamReadings and Stream records are preserved
- `FeedReading` records have a unique constraint on `(channel_id, timestamp)` — duplicate polls within the same interval are silently ignored (idempotent)
- `FeedChannel` records are auto-populated from the provider's endpoint config on provider create/update; dimension values are discovered on first poll (not pre-configured)
- `FeedChannelRuleIndex` is maintained on every rule create/edit/delete — same responsibility as `RuleStreamIndex`; both must be kept in sync
- `scope=system` FeedProviders are polled by a single Celery beat task; no `TenantFeedSubscription` records are created for them
- `RuleCondition` with `condition_type=feed_channel` uses `channel_id` (FK → FeedChannel); `operator` and `threshold_value` follow the same rules as numeric stream conditions
- `RuleCondition` with `condition_type=reference_value` uses `dataset_id` (FK → ReferenceDataset), `value_key` (string — which value_schema field to compare), optional `dimension_overrides` (JSONB — overrides the site's TenantDatasetAssignment dimension_filter for this condition), `operator`, and `threshold_value`
- `ReferenceDatasetRow` resolution order: filter by `dimension_filter` (merged with any `dimension_overrides`) → filter by version (pinned or latest active) → if `has_time_of_use`, filter by current day/time in tenant timezone → if multiple rows match, raise a configuration error (admin must ensure rows are non-overlapping)
- `TenantDatasetAssignment` with `site_id=null` applies tenant-wide; a site-specific assignment (non-null `site_id`) overrides the tenant-wide assignment for that site
- A `TenantDatasetAssignment` must have `effective_to=null` (currently active) for its rows to be used in rule evaluation; expired assignments are retained for audit but not evaluated

---

### Feature: Rule Evaluation Engine

**User Story:** As the platform, I want to evaluate rules automatically and reliably whenever new data arrives or staleness conditions are checked.

**Ingestion-triggered evaluation:**
- [ ] When a StreamReading is saved, a Celery task is dispatched to evaluate rules referencing that stream — ingestion is not blocked by rule evaluation
- [ ] An index (`RuleStreamIndex`) maps each `stream_id` to the rules that reference it — only those rules are evaluated on each new reading, not all rules in the tenant
- [ ] The index is updated whenever a rule is created, edited, or deleted
- [ ] Evaluation latency target: rule fires within 5 seconds of the qualifying reading being ingested
- [ ] When a `FeedReading` is saved, the same pattern applies via `FeedChannelRuleIndex` — rules with `feed_channel` conditions referencing that channel are evaluated immediately
- [ ] `reference_value` conditions are additionally evaluated by a Celery beat task every 5 minutes (catches time-of-use boundary transitions); also evaluated inline when any other condition in the same rule is triggered by a stream or feed reading

**Staleness condition evaluation:**
- [ ] A Celery beat task runs every 60 seconds and checks all active staleness conditions across all tenants
- [ ] Minimum configurable staleness threshold: 2 minutes. Default: 10 minutes. (Thresholds below the beat interval are meaningless)
- [ ] If a stream has not reported within its staleness threshold, the staleness condition is treated as true and the rule is evaluated accordingly

**Rule state and concurrency:**
- [ ] `Rule.current_state` (bool) in the database is the source of truth for whether a rule is currently in a triggered state
- [ ] A Redis atomic flag (`SET rule:{id}:state NX`) acts as a concurrency gate — prevents two Celery workers evaluating the same rule simultaneously from both firing it
- [ ] Worker that successfully sets the Redis flag proceeds with evaluation; worker that finds the flag already set skips firing
- [ ] Redis flag is cleared when the rule condition transitions back to false
- [ ] ⚑ **Flag for deep dive:** Redis atomic flag mechanics — `SET NX`, expiry handling, sync with DB `current_state`, and failure behaviour if Redis is unavailable during evaluation

**Alert generation (when a rule fires):**
- [ ] A single atomic Celery task handles: create Alert record + update `Rule.current_state` + update Redis flag + dispatch notification tasks — wrapped in a DB transaction
- [ ] If the transaction fails, no Alert is created and no notifications are sent — the rule may re-fire on the next qualifying reading

**Rule stream index:**

| Entity | Relationships | Key Fields |
|--------|--------------|------------|
| RuleStreamIndex | links Stream ↔ Rule | id, stream_id, rule_id — maintained automatically, never manually edited |

---

## 5. API & Integration Points

### External Services

| Service | Purpose | Auth Method |
|---------|---------|------------|
| Mosquitto / AWS IoT Core | MQTT broker for Scout device comms — Mosquitto for local dev and self-hosted prod; AWS IoT Core for AWS prod | Mosquitto: username/password; IoT Core: IAM role / device certificates |
| SMTP provider (AWS SES, Mailgun, Postmark, or other) | Transactional email (notifications, invites) — configured via `EMAIL_*` env vars | SMTP credentials or API key (env var) |
| Twilio (or similar — TBC) | SMS notifications | API key (env var) |
| Expo Push Service | Mobile push notifications | Expo push token |
| AWS S3 / MinIO | Object storage — AWS S3 for AWS deployments; MinIO (S3-compatible, self-hosted) for non-AWS deployments. Same code path via `django-storages` — only env vars differ | AWS: IAM role; MinIO: access key / secret key (env var) |

### API Design Patterns
- Style: REST
- Base URL: `/api/v1/`
- Auth: JWT in `Authorization: Bearer <token>` header
- Pagination: cursor-based with `?cursor=` and `?limit=` (default 20, max 100)
- Error format: `{ "error": { "code": "VALIDATION_ERROR", "message": "...", "details": {} } }`
- Date format: ISO 8601 with timezone (UTC)
- Tenant context: resolved from the authenticated user's TenantUser record

### Key Endpoints (MVP)

```
# Auth
POST   /api/v1/auth/login/
POST   /api/v1/auth/refresh/
POST   /api/v1/auth/logout/

# Tenants (That Place Admin only)
GET    /api/v1/tenants/
POST   /api/v1/tenants/
GET    /api/v1/tenants/:id/
PUT    /api/v1/tenants/:id/
POST   /api/v1/tenants/:id/invite/         # send first Admin invite

# Users (Tenant Admin)
GET    /api/v1/users/
POST   /api/v1/users/invite/
PUT    /api/v1/users/:id/
DELETE /api/v1/users/:id/

# Notification Groups (Tenant Admin)
GET    /api/v1/groups/
POST   /api/v1/groups/
GET    /api/v1/groups/:id/
PUT    /api/v1/groups/:id/
DELETE /api/v1/groups/:id/
POST   /api/v1/groups/:id/members/
DELETE /api/v1/groups/:id/members/:user_id/

# Sites
GET    /api/v1/sites/
POST   /api/v1/sites/
GET    /api/v1/sites/:id/
PUT    /api/v1/sites/:id/
DELETE /api/v1/sites/:id/

# Device Types (That Place Admin write, all read)
GET    /api/v1/device-types/
POST   /api/v1/device-types/
GET    /api/v1/device-types/:id/
PUT    /api/v1/device-types/:id/

# Devices
GET    /api/v1/devices/                    # ?site=, ?device_type=, ?status=
POST   /api/v1/devices/
GET    /api/v1/devices/:id/
PUT    /api/v1/devices/:id/
DELETE /api/v1/devices/:id/
POST   /api/v1/devices/:id/approve/        # That Place Admin only
GET    /api/v1/devices/:id/health/
POST   /api/v1/devices/:id/command/
GET    /api/v1/devices/:id/commands/       # command history

# Streams
GET    /api/v1/devices/:id/streams/
GET    /api/v1/streams/:id/
PUT    /api/v1/streams/:id/
GET    /api/v1/streams/:id/readings/       # ?from=, ?to=, ?limit=

# 3rd Party API Provider Library (That Place Admin write, Tenant Admin read)
GET    /api/v1/api-providers/
POST   /api/v1/api-providers/
GET    /api/v1/api-providers/:id/
PUT    /api/v1/api-providers/:id/
DELETE /api/v1/api-providers/:id/

# Data Sources (Tenant Admin)
GET    /api/v1/data-sources/
POST   /api/v1/data-sources/
GET    /api/v1/data-sources/:id/
PUT    /api/v1/data-sources/:id/
DELETE /api/v1/data-sources/:id/
POST   /api/v1/data-sources/:id/discover/            # trigger device discovery, returns device list
GET    /api/v1/data-sources/:id/devices/             # list connected DataSourceDevices
POST   /api/v1/data-sources/:id/devices/             # connect a discovered device (creates or reactivates virtual Device + streams)
PATCH  /api/v1/data-sources/:id/devices/:did/        # update active_stream_keys for a connected device
DELETE /api/v1/data-sources/:id/devices/:did/        # deactivate a device (keeps virtual Device + history)

# Rules
GET    /api/v1/rules/
POST   /api/v1/rules/
GET    /api/v1/rules/:id/
PUT    /api/v1/rules/:id/
DELETE /api/v1/rules/:id/
GET    /api/v1/rules/:id/audit-logs/

# Alerts
GET    /api/v1/alerts/                     # ?status=, ?site=, ?rule=
GET    /api/v1/alerts/:id/
POST   /api/v1/alerts/:id/acknowledge/
POST   /api/v1/alerts/:id/resolve/

# Notifications
GET    /api/v1/notifications/
POST   /api/v1/notifications/:id/read/
GET    /api/v1/notifications/unread-count/

# Dashboards
GET    /api/v1/dashboards/
POST   /api/v1/dashboards/
GET    /api/v1/dashboards/:id/
PUT    /api/v1/dashboards/:id/
DELETE /api/v1/dashboards/:id/
POST   /api/v1/dashboards/:id/widgets/
PUT    /api/v1/dashboards/:id/widgets/:widget_id/
DELETE /api/v1/dashboards/:id/widgets/:widget_id/

# Exports
GET    /api/v1/exports/          # export history log (Admin only)
POST   /api/v1/exports/stream/   # triggers immediate streaming CSV download

# Feed Providers (That Place Admin write, all authenticated read name+description)
GET    /api/v1/feed-providers/
POST   /api/v1/feed-providers/
GET    /api/v1/feed-providers/:id/
PUT    /api/v1/feed-providers/:id/
DELETE /api/v1/feed-providers/:id/
GET    /api/v1/feed-providers/:id/channels/   # list FeedChannels for this provider

# Feed Readings — current values (all authenticated)
GET    /api/v1/feed-channels/:id/readings/    # ?limit=, ?from=, ?to=

# Tenant Feed Subscriptions (Tenant Admin — scope=tenant providers only)
GET    /api/v1/feed-subscriptions/
POST   /api/v1/feed-subscriptions/
GET    /api/v1/feed-subscriptions/:id/
PUT    /api/v1/feed-subscriptions/:id/
DELETE /api/v1/feed-subscriptions/:id/

# Reference Datasets (That Place Admin write, Tenant Admin read)
GET    /api/v1/reference-datasets/
POST   /api/v1/reference-datasets/
GET    /api/v1/reference-datasets/:id/
PUT    /api/v1/reference-datasets/:id/
DELETE /api/v1/reference-datasets/:id/
GET    /api/v1/reference-datasets/:id/rows/
POST   /api/v1/reference-datasets/:id/rows/
PUT    /api/v1/reference-datasets/:id/rows/:row_id/
DELETE /api/v1/reference-datasets/:id/rows/:row_id/
POST   /api/v1/reference-datasets/:id/rows/bulk/   # CSV upload — upserts rows; returns per-row errors; max 10 MB / 50,000 rows
GET    /api/v1/reference-datasets/:id/rows/export/ # CSV download of all rows; cell values sanitised against formula injection; supports ?version= filter

# Tenant Dataset Assignments (Tenant Admin — per site or tenant-wide)
GET    /api/v1/dataset-assignments/           # ?site=
POST   /api/v1/dataset-assignments/
GET    /api/v1/dataset-assignments/:id/
PUT    /api/v1/dataset-assignments/:id/
DELETE /api/v1/dataset-assignments/:id/
GET    /api/v1/dataset-assignments/:id/resolve/  # returns current resolved row(s) for this assignment — useful for previewing what value a rule would see
```

---

## 6. UI/UX Notes

### Target Usage Contexts
- **Primary — Office/remote monitoring (desktop browser):** Council staff, farm managers, operations teams monitoring dashboards, managing devices, building rules, reviewing alerts. Desktop-first layout with rich data density.
- **Secondary — Field operator (on-site, Phase 6 mobile app):** Technicians needing fast access to device status, alerts, and commands while on-site. React Native mobile app — large tap targets, minimal clutter, works in poor conditions.

### Key Screens

**Home / Dashboard**
- Default dashboard with live-refreshing widgets
- Fixed grid layout: 1, 2, or 3 columns (configured per dashboard); single column on mobile
- Widget types: line chart (multi-stream, dual Y-axis), gauge, value card (value + trend + last updated), status indicator, health/uptime chart
- Configurable refresh interval (default 30s), manual refresh button available
- Empty state: prompt to create first widget
- Shared across all tenant users — no per-user dashboards in MVP
- Responsive: widgets reflow to single column on tablet-width browsers (< 1024px)

**Device List**
- Filterable by site and device type
- Each card: name, site, device type, online/offline indicator, last seen
- Shows Scout reference for bridged devices
- Tap to open Device Detail

**Device Detail**
- Header: name, status badge, health summary (battery, signal, last seen, Scout)
- Tabs: Streams | Health | Command History
- Streams tab: list with current value, display enable/disable toggle
- Command button visible to Admin and Operator only

**Rule Builder**
- Step flow: name/description → schedule gate → conditions → actions → review & save
- Schedule gate: multi-select day picker (individual days + Weekdays/Weekends/Every day shortcuts) + optional time window (from/to)
- Condition builder: groups with AND/OR toggle per group; add conditions within groups; top-level AND/OR operator combining groups; one level of nesting maximum
- Stream picker: hierarchical drill-down (site → device → stream); operator options filtered by stream data type; value input adapts to type (number field, toggle, text/dropdown)
- Staleness condition: select stream + enter threshold in minutes/hours
- Action builder: select channels, select groups/users, write message template with variable hints; or select target device + command
- Optional cooldown field on rule: minimum minutes between firings
- Audit trail tab on rule detail screen

**Alert Feed**
- Primary view: active alerts — what is wrong right now
- Separate history tab: all past firings, filterable by site, device, rule, status
- Each card: rule name, triggered at, status badge, site, device
- Tap to view detail; acknowledge/resolve actions for Admin and Operator
- Acknowledge action: single tap + optional free-text "Troubleshooting explanation" field

**Notifications**
- Dropdown panel in nav bar with unread count badge
- Tap a notification to mark it read and navigate to the related alert
- "Mark all as read" button in panel header clears all unread indicators

**Data Export**
- Configure: date window + stream multi-select
- "Download CSV" triggers immediate streaming download
- Export history list (Admin only): exported by, exported at, streams, date range — no download link (re-export to get data again)

### Design Constraints
- Desktop-first — minimum supported width 1024px; responsive down to 768px (tablet browser)
- Dark mode support from day one — semantic colour tokens only, no hardcoded hex in components
- All colours defined in `frontend/src/theme/colors.js`
- Sidebar navigation layout — persistent left nav with collapsible sections
- Max content width: 1440px centred with padding; data-dense views (tables, dashboards) use full width
- Offline: show stale-data indicators, graceful error states — no offline caching in MVP

---

## 7. Development Rules

### Code Standards
- Python: PEP 8, type hints on all function signatures, isort for imports
- JavaScript/React: ESLint with Airbnb config, Prettier for formatting
- Functional components with hooks only — no class components
- Use React Query (TanStack Query) for all API data fetching and caching
- React Router for client-side navigation
- No magic numbers — use named constants
- Use Python `logging` module — never `print()`
- Docstrings on all functions, classes, and components

### Testing
- All API endpoints must have tests: happy path + at least one permission/error case
- Every endpoint that modifies tenant data must have a test confirming cross-tenant access is denied
- Every command endpoint must test that View-Only users are rejected
- Minimum 80% coverage on Django apps
- Use pytest + pytest-django for backend
- Use Jest + React Native Testing Library for frontend

### Environment & Config
- All secrets in `.env`, never committed
- `.env.example` with dummy values committed to repo
- Docker Compose for local development (backend + postgres + redis + mqtt broker + minio)
- Separate Django settings: `base.py`, `dev.py`, `prod.py`, `test.py`
- DataSource credentials encrypted at rest (use Django encrypted fields library)

### Deployment Options

That Place is designed to run on any Linux server. All external service dependencies are configured via environment variables — no AWS SDK calls are hardcoded.

| Component | AWS deployment | Self-hosted deployment |
|-----------|---------------|----------------------|
| Compute | EC2 (ap-southeast-2) | Any Linux VPS or dedicated server |
| Database | RDS PostgreSQL or self-managed | PostgreSQL (Docker or system service) |
| Cache / broker | ElastiCache Redis or self-managed | Redis (Docker or system service) |
| Object storage | AWS S3 | MinIO (S3-compatible, runs in Docker) |
| MQTT broker | AWS IoT Core or Mosquitto | Mosquitto |
| Email | AWS SES | Any SMTP provider (Mailgun, Postmark, etc.) |
| SSL | ACM | Let's Encrypt + Certbot |
| Reverse proxy | ALB or Nginx | Nginx |

**Implementation rule:** All storage operations go through `django-storages`. The backend never calls AWS SDK directly for storage — only the `DEFAULT_FILE_STORAGE` setting and `STORAGES` config change between deployments. MinIO exposes an S3-compatible API, so the same code path works for both.

**Process management:** Production deployments (both AWS and self-hosted) should manage Django, Celery worker, and Celery beat as system services (systemd or Docker Compose). The `docker-compose.yml` used for local dev should be the basis for the production Compose file, with production-appropriate env vars.

### Git Workflow
- Feature branches off `main` — format: `feature/short-description`
- Bugfix branches: `fix/short-description`
- Squash merge to `main`
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`)
- Tag releases: `v1.0.0`, `v1.1.0`, etc.

---

## 8. Milestones & Priority

### Phase 1 — Foundation
- [ ] User auth (JWT login, refresh, logout)
- [ ] Tenant management (That Place Admin creates tenants, sends first Admin invite)
- [ ] Tenant user management with three roles
- [ ] Notification groups (custom + pre-defined system groups)
- [ ] Site management (CRUD)
- [ ] Device Type library (That Place Admin manages, all can read)
- [ ] Device registration with pending/approved provisioning flow
- [ ] Scout gateway reference on bridged device records

### Phase 2 — Data Ingestion & Health
- [ ] MQTT broker integration
- [ ] Celery MQTT ingestion worker (telemetry + health topics)
- [ ] Stream auto-discovery and StreamReading storage
- [ ] Stream display configuration (enable/disable, label/unit override)
- [ ] Device health tracking (all fields) + configurable offline threshold (per device type + per device override)
- [ ] 3rd-party API provider library (That Place Admin)
- [ ] DataSource instances + DataSourceDevice discovery flow (Tenant Admin)
- [ ] Celery beat polling for 3rd-party data sources (discovery + detail endpoints)
- [ ] OAuth2 token refresh handling for oauth2_password and oauth2_client_credentials auth types
- [ ] History endpoint / date-range backfill polling — Phase 3

### Phase 3 — Dashboards & Visualisation
- [ ] Dashboard CRUD
- [ ] Widget types: line chart, gauge, value card, status indicator, health/uptime chart
- [ ] Cross-site / cross-device widgets
- [ ] Configurable time ranges and polling intervals

### Phase 4 — Rules Engine & Alerts
- [ ] Visual rule builder: step flow (name → schedule gate → conditions → actions → review)
- [ ] Schedule gate: multi-select days + optional time window, evaluated in tenant timezone
- [ ] Condition groups with one level of nesting, AND/OR per group, top-level AND/OR combinator
- [ ] Stream conditions with type-gated operators (numeric / boolean / string)
- [ ] Staleness conditions ("stream has not reported in X minutes") — Celery beat evaluation
- [ ] Re-triggering suppression: rule fires on false→true transition only; optional cooldown per rule
- [ ] Rule state tracking (current_state + last_fired_at on Rule model)
- [ ] RuleStreamIndex maintained on rule create/edit/delete
- [ ] Rule evaluation triggered by ingestion events via Celery task (not inline); indexed lookup to find relevant rules only
- [ ] Redis atomic flag for concurrency-safe rule firing (SET NX pattern)
- [ ] Celery beat staleness checker: every 60s, all tenants, minimum threshold 2 minutes
- [ ] Rule audit trail (append-only, before/after field values)
- [ ] Alert generation: active alert model with separate history
- [ ] Alert acknowledge (single tap + optional troubleshooting note) / resolve flow — Admin + Operator only
- [ ] Windowed aggregate conditions (avg/max/min over rolling window) — **Phase 5**

### Phase 4b — Feed Providers & Reference Datasets
- [ ] `FeedProvider` engine: system + tenant scope, JSONB endpoint config, auto-populated `FeedChannel` records, `FeedReading` storage
- [ ] AEMO NEM registered as first `scope=system` FeedProvider; spot prices polling every 5 minutes
- [ ] `FeedChannelRuleIndex` maintained on rule create/edit/delete
- [ ] Feed channel rule conditions: evaluated against latest `FeedReading`; triggers via `FeedChannelRuleIndex`
- [ ] `ReferenceDataset` engine: schema-defined lookup tables with optional TOU and versioning
- [ ] `ReferenceDatasetRow` management (admin UI)
- [ ] `TenantDatasetAssignment` per site (tenant admin UI) with dimension filter + optional version pin
- [ ] Reference value rule conditions: resolved at evaluation time via assignment; beat-evaluated every 5 minutes
- [ ] Seeded on first deployment: `network-tariffs` dataset (all 8 NEM DNSPs), `co2-emission-factors` dataset
- [ ] Rule builder UI extended: feed channel picker and reference value picker in condition builder

### Phase 5 — Notifications, Control & Export
- [ ] In-app notifications + unread badge
- [ ] Email notifications (configurable SMTP backend — AWS SES or any SMTP provider)
- [ ] SMS notifications
- [ ] Mobile push notifications (Expo)
- [ ] Device command sending (manual + rule-triggered) with cmd/ack
- [ ] Command history log
- [ ] CSV data export (on-demand, streaming response, Admin-visible export history log)

### Phase 5b — Notification Enhancements
- [ ] Per-channel opt-out per rule (in addition to global per-channel opt-out)

### Phase 6 — React Native Mobile App
- [ ] React Native (Expo) mobile app — field operator focused
- [ ] Key screens: dashboard viewer, device list + detail, alert feed, acknowledge alert, send command
- [ ] Push notifications via Expo Push Service
- [ ] Offline: cached dashboard view (read-only historical data), graceful degradation
- [ ] Large tap targets, optimised for field use (gloves, poor lighting, small screen)

### Phase 7 — Polish & Scale
- [ ] PDF report builder (user-designed: streams, date windows, graphs, layout)
- [ ] Real-time WebSocket push replacing polling (web + mobile)
- [ ] Data sovereignty configuration (optional, per tenant)
- [ ] Downsampled/aggregated historical data for long-term charts
- [ ] Performance: CDN, query optimisation, read replicas
- [ ] Per-user personal dashboards

### Phase 8 — Future
- [ ] Runner device support (offline rule/schedule execution at the edge)
- [ ] ML/AI rule conditions
- [ ] Rule approval workflows
- [ ] Alert escalation policies
- [ ] Scheduled/email data exports

---

## 9. Open Questions / Flagged Items

- [ ] **SMS provider** — which provider is preferred? (Twilio preferred — works on any deployment. AWS SNS as alternative for AWS-only deployments.)
- [x] **MQTT broker** — resolved: Mosquitto for local dev and self-hosted production deployments. AWS IoT Core supported as an alternative for AWS production deployments. Both use the same ingestion code path — broker connection configured entirely via env vars (`MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`).
- [x] **Legacy telemetry payload format (Scout/telemetry)** — resolved: 12-value CSV string, fixed field order (4 relays, 4 analog inputs, 4 digital inputs). Stream keys match v1 Scout JSON keys. See MQTT Topic Structure section for full mapping.
- [x] **Battery and signal as virtual streams** — resolved: `_battery` and `_signal` are reserved keys in v1 Scout telemetry. Stored as StreamReadings (virtual streams) AND update DeviceHealth. Makes them available to rule engine and dashboard without special handling. Legacy v1 devices have null battery/signal.
- [x] **Activity level thresholds** — resolved: configurable per tenant via Tenant model fields with platform defaults (signal: -70/-85 dBm, battery: 40%/20%, offline approaching: 75%). See Feature: Device Health Monitoring for full derivation rules.
- [ ] ⚑ **Legacy weatherstation/tbox/abb payload format** — payload structure for these three legacy message types still required before their parsers can be built. Hardware team input needed.
- [ ] ⚑ **Legacy command format** — current command format sent to Scouts is inconsistent (strings, JSON, raw characters). Clarify with hardware team and define migration path before legacy command handling can be specced.
- [ ] **Scout firmware rollout plan** — ~500 Scouts across ~30 customers need firmware updates to move from `legacy_v1` to `that_place_v1` topic format. Dual-format support handles the transition period. Coordinate update timeline and rollout order with hardware team.
- [ ] **Existing customer migration** — post-launch activity. No migration tooling required for MVP. Approach to be planned separately.
- [ ] **Dashboard public/shared links** — is sharing a dashboard view (read-only link) ever needed?
- [ ] ⚑ **Unknown condition state** — when a stream referenced in a rule condition stops reporting, the last known value is used OR the condition is treated as unknown/false. Decision: if a stream goes stale, should point-in-time conditions using that stream be treated as false (rule cannot fire) or continue using the last known value? Staleness conditions handle the "offline sensor" case explicitly, but this edge case remains for standard stream conditions.
- [ ] ⚑ **Additional stream types** — beyond Numeric / Boolean / String/Enum. Candidates include GPS coordinates, images, compound/structured values. Some types may not be usable in rule conditions even if they exist as streams. Revisit when designing the device type library in detail.
- [x] **3rd party API — bulk device management UX** — resolved: two-phase wizard. Phase A: tenant sets a default site for all discovered devices with per-device site override, selects devices via checkboxes (select-all supported). Phase B: stream activation configured as a batch across all selected devices; per-device overrides available later via the device detail Streams tab. Post-connection management page shows all connected devices with add/deactivate actions. See Feature: Data Ingestion — 3rd Party APIs for full detail.
- [ ] ⚑ **3rd party API — history endpoint** — some providers offer a date-range endpoint for historical data (e.g. `/history/?from=&to=`). Phase 2 item: design a backfill polling pattern that does not conflict with the regular detail endpoint polling.
- [ ] ⚑ **3rd party API — poll dispatch race condition** — the Celery beat task checks `last_polled_at` from the DB to decide if a device is due, but `last_polled_at` is only written back after `poll_single_device` completes. If a poll task runs longer than the beat interval (30 s) — possible under provider slowness or network stalls (worst case: `REQUEST_TIMEOUT × MAX_AUTH_RETRIES = 45 s`) — the next beat tick will see the stale `last_polled_at`, consider the device overdue, and dispatch a second concurrent task. This produces duplicate `StreamReading` rows for that cycle. Mitigations to consider: (a) set a `dispatched_at` sentinel field in the beat task before dispatching so subsequent ticks skip it, (b) use `select_for_update()` on the due-check query, or (c) add a DB unique constraint on `(stream_id, timestamp)` in `StreamReading` to make duplicates a no-op. Address before scaling to large fleets or short poll intervals.
- [ ] ⚑ **Notification event registry** — system event notifications should be registered centrally rather than hardcoded. Architectural design required during Phase 5 implementation — how event types are registered, what metadata they carry, and how they map to notification templates.
- [ ] ⚑ **That Place Admin notification channel** — delivery mechanism (in-app, email, external alerting tool) and full platform event list to be defined in a dedicated deep dive before Phase 5.
- [ ] ⚑ **Notification retention at scale** — currently retained forever consistent with raw data policy. Revisit if notification volume becomes a storage concern.
- [ ] ⚑ **Redis atomic flag deep dive** — before implementing the rule evaluation engine, review how `SET NX` works in practice: key naming, TTL/expiry strategy to prevent stale locks if a worker crashes mid-evaluation, how the Redis flag stays in sync with `Rule.current_state` in the DB, and degraded behaviour if Redis is temporarily unavailable.
