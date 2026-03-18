# 3rd Party API Provider Registration Guide

This guide is for **Fieldmouse Admins** adding a new data provider to the platform library.
Once a provider is registered, any Tenant Admin can connect their account and start pulling
device data without further involvement from Fieldmouse Admin.

For the technical specification see `SPEC.md § Feature: Data Ingestion — 3rd Party APIs`.

---

## Overview

Adding a provider is a one-time configuration task. You are telling the platform:

1. **How to authenticate** — what credentials tenants will enter and how to use them
2. **How to discover devices** — which endpoint lists the devices on an account
3. **How to read data** — which endpoint returns current readings for a single device
4. **What streams are available** — the data fields the platform should capture

---

## Step-by-step

Navigate to **FM Admin → API Provider Library → New Provider**.

---

### 1. Basic info

| Field | Notes |
|-------|-------|
| **Name** | Display name shown to Tenant Admins. E.g. `SoilScout` |
| **Slug** | URL-safe identifier. Auto-suggested from name. Must be unique. E.g. `soilscout` |
| **Description** | One or two sentences shown to tenants when picking a provider. |
| **Logo** | Upload a logo image. Stored in S3/MinIO. Shown in the provider picker. |
| **Base URL** | Root URL for all API calls. No trailing slash. E.g. `https://soilscouts.fi/api/v1` |

---

### 2. Auth type

Choose how the provider authenticates requests. This controls which fields appear below.

| Auth type | When to use | Tenant enters |
|-----------|-------------|---------------|
| **API Key (Header)** | Provider issues a static key sent as a request header | The header name and key value |
| **API Key (Query Param)** | Provider issues a static key sent as a URL query parameter | The param name and key value |
| **Bearer Token** | Provider issues a static token used as `Authorization: Bearer` | The token |
| **Basic Auth** | Provider uses HTTP Basic Auth | Username and password |
| **OAuth2 Client Credentials** | Machine-to-machine OAuth2 — no user login | Client ID and secret |
| **OAuth2 Password Grant** | OAuth2 with a user login (username + password → JWT) | Username and password |

#### OAuth2 fields (only shown for OAuth2 auth types)

| Field | Notes |
|-------|-------|
| **Token URL** | The endpoint the platform POSTs to in order to obtain an access token. E.g. `https://soilscouts.fi/api/v1/auth/login/` |
| **Refresh URL** | Leave blank if the provider uses the same endpoint for refresh. Fill in only if the refresh endpoint is different from the Token URL. E.g. `https://soilscouts.fi/api/v1/auth/token/refresh/` |

> Token and refresh URLs are provider-level config — tenants never see or enter them.
> Tenant credentials contain only what the tenant personally knows (username, API key, etc.).

---

### 3. Credential fields (auth param schema)

This defines the form a Tenant Admin fills in when connecting their account.
Add one entry per credential field.

| Property | Notes |
|----------|-------|
| **key** | Internal identifier. Used as the dict key when the platform sends credentials to the auth handler. E.g. `username`, `api_key`, `X-API-Key` |
| **label** | Human-readable label shown in the form. E.g. `SoilScout Username` |
| **type** | `text` for plain-text fields; `password` for masked fields |
| **required** | Tick if the field must be filled in before the tenant can connect |

**Examples by auth type:**

_API Key (Header)_ — key is the header name, value is what the tenant enters:
```
key: X-API-Key   label: API Key   type: password   required: yes
```

_OAuth2 Password Grant_ — tenant enters their login credentials:
```
key: username   label: Username / Email   type: text      required: yes
key: password   label: Password           type: password  required: yes
```

_OAuth2 Client Credentials_ — tenant enters machine credentials:
```
key: client_id      label: Client ID      type: text      required: yes
key: client_secret  label: Client Secret  type: password  required: yes
```

---

### 4. Discovery endpoint

The platform calls this endpoint once (on tenant request) to list all devices on the account.
The response is shown to the Tenant Admin so they can choose which devices to connect.

| Field | Notes |
|-------|-------|
| **Path** | Endpoint path, appended to Base URL. E.g. `/devices/` |
| **Method** | Usually `GET` |
| **Device ID JSONPath** | JSONPath expression that extracts the list of device IDs from the response. E.g. `$[*].id` |
| **Device name JSONPath** | Optional. Extracts display names for devices. Leave blank if the provider doesn't return names. E.g. `$[*].name` |

**JSONPath tips:**

| Response shape | ID path | Name path |
|----------------|---------|-----------|
| Flat array: `[{id, name}, ...]` | `$[*].id` | `$[*].name` |
| Paginated: `{results: [{id, name}, ...]}` | `$.results[*].id` | `$.results[*].name` |
| Nested: `{data: {devices: [{id}, ...]}}` | `$.data.devices[*].id` | — |

The ID and name paths must return lists of the same length in the same order.

---

### 5. Detail endpoint

The platform calls this endpoint once per connected device on every poll cycle.
It must return the current readings for a single device.

| Field | Notes |
|-------|-------|
| **Path template** | Path with `{device_id}` as a placeholder. E.g. `/devices/{device_id}/?with_details` |
| **Method** | Usually `GET` |

> If the provider uses query parameters for device selection rather than a path segment
> (e.g. `/readings/?device=123`), use `{device_id}` in the query string:
> `/readings/?device={device_id}&latest=true`

---

### 6. Available streams

Each stream is one data field the platform can capture from the detail endpoint response.
Tenant Admins choose which streams to activate per device when they connect.

| Property | Notes |
|----------|-------|
| **key** | Internal identifier. Becomes the `Stream.key` on virtual devices. E.g. `moisture` |
| **label** | Default display label. Tenants can override per device. E.g. `Soil Moisture` |
| **unit** | Default display unit. Tenants can override per device. E.g. `m³/m³` |
| **data_type** | `numeric` (default), `boolean`, or `string` |
| **JSONPath** | Expression to extract this field's value from the detail endpoint response. E.g. `$.last_measurement.moisture` |

**JSONPath tips:**
- Expressions are evaluated against the full JSON body returned by the detail endpoint
- Use `$.field` for top-level fields
- Use `$.nested.field` for nested objects
- Only the first match is used — the expression should return a scalar value, not a list

---

### 7. Poll interval

How often (in seconds) the platform polls each connected device. Default: `300` (5 minutes).
Set this to match the provider's data update frequency — polling faster than the provider
publishes data wastes API calls and may hit rate limits.

| Provider cadence | Suggested interval |
|------------------|--------------------|
| Real-time / 1 min | 60–120 |
| 5 min | 300 |
| 15 min | 900 |
| Hourly | 3600 |

---

## After saving

- The provider appears in the Tenant Admin provider picker immediately
- Existing connected DataSources are unaffected by edits to a provider
- You can deactivate a provider (`is_active = false`) to hide it from new connections without breaking existing ones
- You cannot delete a provider that has active DataSources — deactivate the DataSources first

---

## Registered providers

| Provider | File |
|----------|------|
| SoilScout | [soilscout.md](soilscout.md) |
