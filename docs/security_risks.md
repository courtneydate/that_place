# That Place — Security Risk Register

> Generated from SPEC.md v5.1 and ROADMAP.md review.
> Work through each item in priority order — mark status as risks are resolved.

---

## Status Key

| Status | Meaning |
|--------|---------|
| `OPEN` | Not yet addressed |
| `IN PROGRESS` | Mitigation being implemented |
| `RESOLVED` | Mitigation implemented and tested |
| `ACCEPTED` | Risk accepted with documented rationale |

---

## Critical

### SR-01 — MQTT Topic Spoofing / Device Impersonation
**Status:** `RESOLVED`
**Sprint:** 6

**Risk:** The backend subscribes to `that-place/scout/+/#` and trusts the serial number embedded in the topic string. If Mosquitto is not configured with per-client ACLs (each Scout restricted to publishing only on its own serial's topics), any authenticated MQTT client on the broker can publish data as any other device. A compromised Scout could inject false telemetry for devices belonging to other tenants.

**Resolution:**
- `docker/mosquitto/mosquitto.conf` — `allow_anonymous false`; Mosquitto 2.0 Dynamic Security plugin enabled
- `docker/mosquitto/entrypoint.sh` — bootstraps `dynamic-security.json` on first start using `MQTT_ADMIN_USERNAME` / `MQTT_ADMIN_PASSWORD`
- `docker-compose.yml` — mosquitto service uses custom entrypoint, env vars passed through
- `backend/apps/ingestion/mqtt_credentials.py` — `MQTTCredentialService` provisions/revokes per-Scout credentials via the `$CONTROL/dynamic-security/v1` topic
- `backend/apps/devices/signals.py` + `apps.py` — signal on Device save: provision on approval, revoke on deactivation/rejection
- `backend/apps/devices/models.py` + migration `0006` — `mqtt_password` (EncryptedTextField) stores provisioned credential for handoff to device operator
- `.env.example` + `settings/base.py` — `MQTT_ADMIN_USERNAME` / `MQTT_ADMIN_PASSWORD` documented and wired

**Enhanced:** mTLS client certificate support added on port 8883 alongside the existing password flow on port 1883.
- `docker/mosquitto/entrypoint.sh` — generates self-signed CA + broker cert in dev; in prod, accepts `MQTT_CA_CERT_B64` / `MQTT_CA_KEY_B64` / `MQTT_BROKER_CERT_B64` / `MQTT_BROKER_KEY_B64` env vars
- `backend/apps/ingestion/pki.py` — `issue_device_certificate()` generates RSA 2048 key pair, signs cert with CA, sets CN=`scout-{serial}` for `use_subject_as_username` ACL mapping
- `Device.mqtt_auth_mode` field — `password` (default, port 1883) or `certificate` (port 8883)
- `Device.mqtt_certificate` + `Device.mqtt_private_key` (encrypted) fields — store issued cert and key for operator handoff
- `MQTTCredentialService.provision_device()` routes to password or certificate flow based on `mqtt_auth_mode`

**Remaining:** A `provision_all_mqtt_clients` management command is needed to back-fill credentials for devices that were already active before this change was deployed. To be added before production deployment.

---

### SR-02 — Third-Party API Credential Storage
**Status:** `RESOLVED`
**Sprint:** 10

**Risk:** OAuth2 credentials (access tokens, refresh tokens, and potentially raw username/password under the password grant flow) for DataSource integrations are stored in the database. If stored in plaintext, a DB breach exposes all connected tenant credentials to third-party services. The password grant flow (explicitly called out in Sprint 10) compounds this — live authenticating credentials are held at rest.

**Resolution:**
- `apps/integrations/fields.py` — `EncryptedJSONField` built on `django-encrypted-model-fields` `EncryptedTextField` (Fernet symmetric encryption)
- `apps/integrations/models.py` — `DataSource.credentials` and `DataSource.auth_token_cache` both use `EncryptedJSONField`
- `apps/feeds/models.py` — `TenantFeedSubscription.credentials` uses `EncryptedJSONField`
- `apps/integrations/serializers.py` — `DataSourceSerializer.credentials` is `write_only=True`; `auth_token_cache` is excluded from the serializer entirely
- `config/settings/base.py` — `FIELD_ENCRYPTION_KEY = env('FIELD_ENCRYPTION_KEY')` wired from environment
- `.env.example` — `FIELD_ENCRYPTION_KEY` documented with generation command
- `backend/requirements/base.txt` — `django-encrypted-model-fields>=0.6` pinned
- `apps/integrations/tests/test_datasources.py` — `TestCredentialEncryptionAtRest` class verifies: raw DB column does not contain plaintext, ORM decrypts correctly on read, credentials absent from all API responses

**Password grant note:** `oauth2_password` auth type (`ThirdPartyAPIProvider.AuthType.OAUTH2_PASSWORD`) stores live username/password credentials in `DataSource.credentials`. These are now encrypted at rest. Where a provider adds OAuth2 client credentials or authorization code support in future, credentials should be migrated — the `auth_type` field on the provider record documents which flow is in use. Providers confirmed to require password grant: SoilScout (`/auth/login/` endpoint, no client credentials flow available at time of writing).

---

### SR-03 — Tenant Isolation in Celery Beat Tasks
**Status:** `RESOLVED`
**Sprint:** 8, 16, 17

**Risk:** Beat tasks (staleness checker, rule re-evaluation, feed polling) operate without a `request.user` context. If queryset filtering by `tenant_id` is not explicitly threaded through every ORM call inside those tasks, cross-tenant data leaks silently — with no HTTP 403, no visible error, and no test failure unless a cross-tenant test is written for the task specifically.

**Resolution:**
All beat tasks were audited. The dispatch tasks (`check_devices_offline`, `poll_datasource_devices`, `poll_tenant_subscriptions`, `evaluate_reference_value_rules`) are intentionally global — they process all tenants by design. Cross-tenant isolation is guaranteed structurally: per-item tasks receive a single PK, and all related data is accessed via FK chains that are scoped to the owning tenant. No ORM call reads data from one tenant and writes it to another.

Cross-tenant isolation tests added to verify this structurally:

- `backend/apps/devices/tests/test_tasks.py` — `TestCheckDevicesOfflineCrossTenant`
  - Stale device → goes offline; adjacent fresh device → stays online
  - Multiple tenants in mixed states all resolved independently
  - Inactive devices excluded from processing

- `backend/apps/integrations/tests/test_isolation.py` — `TestPollSingleDeviceCrossTenant`
  - StreamReadings written only to the polled tenant's virtual device
  - `last_polled_at` / `last_poll_status` only updated on the polled DSD
  - Poll failure on Tenant A does not increment Tenant B's failure counter

- `backend/apps/feeds/tests/test_tasks.py` — `TestPollSingleSubscriptionCrossTenant` + `TestEvaluateReferenceValueRules`
  - Polling Sub A does not update Sub B's `last_polled_at` or add to Sub B's channels' readings
  - `evaluate_reference_value_rules` dispatches evaluation for all tenants' active reference_value rules and excludes inactive rules and stream-only rules

---

## High

### SR-04 — CSV Bulk Import — Injection and Resource Exhaustion
**Status:** `RESOLVED`
**Sprint:** 15a

**Risk:** `POST /api/v1/reference-datasets/:id/rows/bulk/` accepts CSV file uploads. Two vectors: (a) Formula injection — if uploaded values contain `=`, `+`, `-`, or `@` characters and the data is later exported to CSV and opened in Excel/Sheets, they execute as formulas. (b) No upload size or row count limit is specified — a large file could exhaust memory in the Celery worker processing it.

**Resolution:**

**(a) Formula injection (export-time sanitisation):**
- `apps/feeds/serializers.py` — `sanitize_csv_cell(value)` utility: prefixes any cell value starting with `=`, `+`, `-`, or `@` with a tab character, preventing spreadsheet formula execution on import
- `apps/feeds/views.py` — `GET /api/v1/reference-datasets/:id/rows/export/` action added to `ReferenceDatasetRowViewSet`; calls `sanitize_csv_cell` on every string cell before writing the CSV response; returns `Content-Disposition: attachment` with `text/csv` content type
- `apps/feeds/urls.py` — `reference-datasets/<dataset_pk>/rows/export/` route wired up

**(b) Resource exhaustion limits (import-time enforcement):**
- `apps/feeds/serializers.py` — `CSV_MAX_UPLOAD_BYTES = 10 MB` constant; `validate_file()` rejects files exceeding this limit with a 400 before any parsing
- `apps/feeds/serializers.py` — `CSV_MAX_ROWS = 50,000` constant; `import_rows()` materialises all rows upfront and returns a 400 if the count exceeds the limit, preventing streaming exhaustion

**Tests:**
- `apps/feeds/tests/test_sprint15a.py` — `BulkImportLimitsTest`: file over 10 MB rejected, file at limit accepted, row count over 50k rejected, non-CSV rejected
- `apps/feeds/tests/test_sprint15a.py` — `SanitizeCsvCellTest`: each formula-triggering character prefixed, safe values unchanged
- `apps/feeds/tests/test_sprint15a.py` — `CsvExportTest`: CSV content type, attachment disposition, formula value sanitised in output, safe values unmodified, row count matches DB, tenant user forbidden

---

### SR-05 — Invite Token Security
**Status:** `RESOLVED`
**Sprint:** 1, 3

**Risk:** The spec calls for invite token generation but does not specify entropy, TTL, or single-use enforcement. If tokens are short, sequential, or long-lived, an attacker who intercepts or enumerates a token can create an account under an arbitrary tenant.

**Resolution:**
- `apps/accounts/models.py` — `TenantInvite` model: stores `token_hash` (SHA-256 hex, 64 chars, `unique=True`), `email`, `role`, `tenant` FK, `created_by` FK, `expires_at`, `used_at` (nullable), `created_at`
- `TenantInvite.generate()` class method: generates raw token via `secrets.token_urlsafe(32)` (256-bit entropy), computes `hashlib.sha256(raw.encode()).hexdigest()`, persists only the hash. Returns `(invite, raw_token)` — raw token is never stored.
- `expires_at` set to `timezone.now() + timedelta(hours=72)` — 72-hour TTL
- `apps/accounts/serializers.py` — `AcceptInviteSerializer.validate_token()` looks up `TenantInvite` by SHA-256 hash of the submitted token; rejects if not found (invalid), `is_used` (already accepted), `is_expired` (TTL elapsed), or tenant inactive
- `AcceptInviteSerializer.create()` — sets `invite.used_at = timezone.now()` atomically with user creation — single-use enforcement
- `apps/accounts/views.py` — both `TenantViewSet.invite` and `UserViewSet.invite` replaced `signing.dumps()` with `TenantInvite.generate()`; raw token sent in URL, never stored; email updated to say "expires in 72 hours"
- `apps/accounts/migrations/0006_tenantinvite.py` — migration creating the table
- `apps/accounts/tests/test_users.py` — `TestAcceptInvite` updated: `make_invite()` helper creates DB record; new tests: `test_invite_marked_used_after_accept`, `test_token_cannot_be_used_twice`; existing tests updated to use DB-backed tokens

---

### SR-06 — Message Template Injection in Rule Actions
**Status:** `OPEN`
**Sprint:** 15

**Risk:** Notification rule actions include a message template with variable interpolation. If the template renderer uses Python `str.format()` or similar without sandboxing, a crafty Tenant Admin can craft a template that reads arbitrary object attributes — a well-documented Python format-string vulnerability (e.g. `{object.__class__.__init__.__globals__}`).

**Mitigation target:** Use Jinja2 in sandbox mode (`SandboxedEnvironment`) with a restricted variable context. Never use `str.format()` or f-strings with user-supplied template strings.

---

### SR-07 — Device Command Parameter Validation
**Status:** `OPEN`
**Sprint:** 21

**Risk:** Device commands are validated against the device type's param schema (JSONB), then published to MQTT. If param values are not strictly type-checked and range-validated against the schema before publishing, a crafted command could send malformed MQTT payloads or trigger unexpected firmware behaviour at the Scout level.

**Mitigation target:** Serializer-level validation must enforce each param's declared type (number/toggle/text), min/max bounds, and maximum string length before any MQTT publish. Reject and return 400 if any param fails validation — never publish a partially valid command.

---

## Medium

### SR-08 — Feed Provider JSONPath Evaluation
**Status:** `RESOLVED`
**Sprint:** 15a

**Risk:** FeedReading values are extracted from API responses via JSONPath expressions configured by That Place Admin. Some JSONPath libraries support filter expressions that permit arbitrary code evaluation. If the chosen library allows this and expressions come from DB-stored config, a compromised admin account could trigger code execution via a crafted JSONPath expression.

**Resolution:**
- All three call sites switched from `from jsonpath_ng.ext import parse` to `from jsonpath_ng import parse`: `apps/feeds/tasks.py`, `apps/integrations/tasks.py`, `apps/integrations/views.py`
- The core `jsonpath_ng` parser supports standard path navigation (`$.field`, `[*]`, `$.results[*].id`) — all expressions currently in production use — but raises a parse error on filter expressions (`?(@.price > 100)`) and arithmetic expressions, so they cannot be evaluated even if stored in provider config by a compromised admin account
- All existing JSONPath expressions in the codebase (`$.PRICE`, `$.ELEC_NEM_SUMMARY[*]`, `$.results[*].id`, `$.soil_moisture`, etc.) work identically with the core parser — no behaviour change
- `apps/feeds/tests/test_jsonpath_security.py` — `TestJsonPathLibrarySecurity`: verifies standard path expressions work, asserts filter and arithmetic expressions raise parse errors, and asserts none of the three call sites import from `jsonpath_ng.ext`

---

### SR-09 — That Place Admin Access — No Audit Trail
**Status:** `OPEN`
**Sprint:** All phases

**Risk:** That Place Admins can access any tenant's data for support purposes. No audit log for these cross-tenant accesses is specified. This is a compliance gap — Australian Privacy Act and similar regulations require that access to personal/organisational data be logged.

**Mitigation target:** Log all That Place Admin cross-tenant data access: who accessed, which tenant, which endpoint, timestamp. Store in an append-only audit log table. Expose a read-only audit log endpoint for That Place Admins only.

---

### SR-10 — Redis Unauthenticated in Dev / Rule State Manipulation
**Status:** `OPEN`
**Sprint:** 16

**Risk:** The Redis `SET rule:{id}:state NX` flag is the concurrency and re-trigger guard for rule evaluation. In development, Redis commonly runs without a password and bound to `0.0.0.0`. If this bleeds into staging or a misconfigured prod environment, an attacker can clear or forge rule state keys — causing rules to fire repeatedly (notification flood) or be silently suppressed (missed alerts).

**Mitigation target:** Enforce `requirepass` in Redis config for all environments. Add `REDIS_PASSWORD` to `.env.example` as a required variable. Confirm the Docker Compose Redis service is bound to `127.0.0.1` only, not `0.0.0.0`.

---

### SR-11 — Push Notification Token Exposure
**Status:** `OPEN`
**Sprint:** 24

**Risk:** Expo push tokens stored on user profiles act as credentials — anyone with a token can push a notification to that user's device. If tokens are returned in user list or profile API responses, they are exposed to other users within the same tenant (e.g., an Operator reading the user list).

**Mitigation target:** Never return push tokens in any API response. Tokens are write-only from the client — stored server-side and never read back. Revoke (clear) the stored token on logout.

---

### SR-12 — CSV Export Formula Injection
**Status:** `OPEN`
**Sprint:** 22

**Risk:** The CSV export writes stream keys and values directly from the database. If a device reports a stream value containing `=SUM(...)`, `+cmd`, or similar formula-triggering strings, those values appear verbatim in the exported file. Opening the file in Excel or Sheets executes the formula — a CSV injection attack.

**Mitigation target:** On CSV row write, prefix any cell value that begins with `=`, `+`, `-`, or `@` with a tab character (`\t`) or wrap in quotes to prevent formula execution. Apply to both stream keys and values.

---

## Lower / Design-Level

### SR-13 — OAuth2 Password Grant (Deprecated Flow)
**Status:** `OPEN`
**Sprint:** 10

**Risk:** The password grant flow is removed in OAuth 2.1 — it requires storing the tenant's raw username and password for the provider, which That Place then holds on their behalf. This increases credential exposure and liability.

**Mitigation target:** For each provider integration, prefer client credentials or authorization code flow where supported. Document where password grant is unavoidable (provider limitation) and ensure those credentials are encrypted at rest (see SR-02). Flag for migration when the provider adds a better flow.

---

### SR-14 — Offline Threshold — Alert Flood Vector
**Status:** `OPEN`
**Sprint:** 8

**Risk:** Tenant Admin can set an arbitrarily short offline threshold per device. No minimum is specified. A threshold of 1–2 seconds would cause the beat task to mark every device offline on every cycle, generating a notification flood that could degrade platform performance and spam users.

**Mitigation target:** Enforce a minimum offline threshold (e.g. 2 minutes) at the serializer level. Return a 400 error if a value below the minimum is submitted. Mirror the same minimum enforcement used for staleness conditions (Sprint 17 already specifies a 2-minute minimum there).

---

### SR-15 — Permission Enforcement at Service Layer
**Status:** `OPEN`
**Sprint:** 16, 18, 21

**Risk:** Role-based permission checks (e.g. View-Only cannot send commands, cannot acknowledge alerts) are enforced on HTTP endpoints. If any Celery task or internal service function is called directly — bypassing the view layer — those permission checks are skipped.

**Mitigation target:** Critical permission checks (command send, alert acknowledge, rule modification) must be enforced at the model/service layer in addition to the view layer. Internal callers should pass an explicit actor and have permissions validated before the action executes.

---

*Last updated: 2026-04-15 — SR-01, SR-02, SR-03, SR-04, SR-05, SR-08 resolved*
