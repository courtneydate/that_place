# That Place — Development Roadmap

> Reflects SPEC.md v5.0. Sprints are sequenced as vertical slices — each sprint delivers
> working backend, frontend, and tests for a complete feature before the next sprint begins.
>
> **Rule:** A sprint is not complete until its Definition of Done is fully satisfied.
> No new sprint starts until the current one is signed off.

---

## Conventions

- Each sprint is 1–2 weeks depending on complexity
- Backend API is built and tested before frontend consumes it
- Every sprint includes: models → serializers → views → tests → frontend → smoke test
- Sprints are numbered, not dated — attach dates when planning begins

---

## Sprint 0 — Project Setup

**Goal:** A working local development environment and CI pipeline before any feature code is written.

**Deliverables:**
- [x] Docker Compose stack: Django, PostgreSQL, Redis, Celery worker, Celery beat, Mosquitto (MQTT), MinIO (object storage), React dev server
- [x] Django project structure: apps (`accounts`, `devices`, `ingestion`, `readings`, `rules`, `alerts`, `dashboards`, `notifications`), split settings (`base`, `dev`, `prod`, `test`)
- [x] React (Vite) project structure: `pages/`, `components/`, `hooks/`, `services/`, `theme/`
- [x] `.env.example` with all required variables documented
- [x] GitHub Actions CI: lint (flake8, isort, eslint) + **full** test suite (pytest + jest, all apps, all sprints) on every PR — fails and blocks merge on any single test failure
- [x] Base test configuration: pytest-django, factory-boy for fixtures, Jest + React Testing Library
- [x] README.md with setup instructions

**Definition of Done:**
- `docker-compose up -d` brings up all services with no errors
- `pytest` runs with 0 failures on an empty test suite
- `npm test` runs with 0 failures on an empty test suite
- A PR to `main` triggers CI and blocks merge on failure

---

## Phase 1 — Foundation

### Sprint 1 — Authentication

**Goal:** Users can log in, stay logged in, and log out securely.

**Deliverables:**
- [x] Backend: `User` model, JWT login / token refresh / logout endpoints (SimpleJWT)
- [x] Backend: Token blacklist on logout
- [x] Backend: `IsAuthenticated` base permission class applied globally
- [x] Backend: Tests — login happy path, invalid credentials, expired token, logout blacklists token
- [x] Frontend: Login page (email + password form, validation, error states)
- [x] Frontend: Auth context — stores tokens, auto-refreshes before expiry, clears on logout
- [x] Frontend: Protected route wrapper — redirects unauthenticated users to login

**Definition of Done:**
- Can log in with valid credentials
- Invalid credentials show a clear error message
- Token refreshes silently in the background
- Logout clears session and redirects to login
- Accessing a protected route while unauthenticated redirects to login

---

### Sprint 2 — Tenant Management (That Place Admin)

**Goal:** That Place Admin can create tenants and send the first admin invite.

**Deliverables:**
- [x] Backend: `Tenant` model (with timezone field), `TenantUser` model
- [x] Backend: That Place Admin guard (`IsThat PlaceAdmin` permission class)
- [x] Backend: Tenant CRUD endpoints (That Place Admin only)
- [x] Backend: Invite endpoint — generates invite token, sends email via configured email backend
- [x] Backend: Tests — CRUD happy path, non-admin access denied, invite sent, duplicate tenant slug rejected
- [x] Frontend: That Place Admin layout (separate nav from tenant user layout)
- [x] Frontend: Tenant list page, create tenant form, tenant detail / edit page
- [x] Frontend: Send invite action on tenant detail

**Definition of Done:**
- That Place Admin can create, view, edit, and deactivate tenants
- Invite email is sent to the first Tenant Admin
- Non-That Place-Admin users cannot access tenant management endpoints (403 returned)
- Deactivated tenant users cannot log in

---

### Sprint 3 — Tenant User & Role Management

**Goal:** Tenant Admin can manage their organisation's users and roles.

**Deliverables:**
- [x] Backend: Invite accept flow (set password from invite token)
- [x] Backend: User list, role update, remove user endpoints — scoped to tenant
- [x] Backend: `IsTenantAdmin`, `IsOperator`, `IsViewOnly` permission classes
- [x] Backend: Tenant context middleware — resolves tenant from authenticated user
- [x] Backend: Tests — invite flow, role change, removal, cross-tenant access denied, View-Only blocked from write endpoints
- [x] Frontend: Accept invite page (set password)
- [x] Frontend: User management page (list, invite, change role, remove)

**Definition of Done:**
- Invited user can accept invite and set their password
- Tenant Admin can invite, promote, demote, and remove users
- All role permission rules enforced on API (tested with cross-tenant and cross-role requests)
- Removed user immediately loses API access

---

### Sprint 4 — Tenant Settings, Sites & Notification Groups

**Goal:** Tenant Admin can configure their organisation's timezone, create sites, and manage notification groups.

**Deliverables:**
- [x] Backend: Tenant settings endpoint (update timezone)
- [x] Backend: Site CRUD endpoints (scoped to tenant)
- [x] Backend: `NotificationGroup` + `NotificationGroupMember` models and endpoints
- [x] Backend: Auto-maintained system groups (All Users, All Admins, All Operators) — derived from TenantUser roles
- [x] Backend: Tests — site isolation, system group membership auto-updates on role change
- [x] Frontend: Tenant settings page (timezone picker)
- [x] Frontend: Site management page (list, create, edit, delete)
- [x] Frontend: Notification groups page (list, create, manage members)

**Definition of Done:**
- Tenant Admin can set timezone — persists and is returned on API responses
- Sites are isolated per tenant — Tenant A cannot see Tenant B's sites
- System groups reflect current user roles automatically
- Custom groups can be created with arbitrary members

---

### Sprint 5 — Device Type Library & Device Registration

**Goal:** That Place Admin can define device types; Tenant Admin can register devices and go through the approval flow.

**Deliverables:**
- [x] Backend: `DeviceType` model (with commands JSONB, stream type definitions, offline threshold, ack timeout)
- [x] Backend: DeviceType CRUD (That Place Admin write, all authenticated read)
- [x] Backend: `Device` model (with `topic_format`, `offline_threshold_override_minutes`, `gateway_device_id`)
- [x] Backend: Device registration endpoint (creates device with status `pending`)
- [x] Backend: Device approval endpoint (That Place Admin only)
- [x] Backend: Tests — approval flow, pending device cannot ingest data, cross-tenant device isolation
- [x] Frontend: Device type library page (That Place Admin — create/edit types, define commands and stream types)
- [x] Frontend: Device registration form (Tenant Admin — name, serial, site, device type)
- [x] Frontend: Pending device indicator + That Place Admin approval action
- [x] Frontend: Device list page with status badges

**Definition of Done:**
- That Place Admin can create device types with stream type definitions and commands
- Tenant Admin can register a device — it appears as pending
- That Place Admin can approve or reject — approved devices become active
- Unapproved devices cannot submit data (API rejects with 403)

---

**Phase 1 Sign-Off Checklist:**
- [ ] All Sprint 0–5 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: complete onboarding flow (create tenant → invite admin → set up site → register device → approve device)
- [ ] Cross-tenant isolation confirmed: Tenant A user cannot access Tenant B data on any endpoint
- [ ] Role permission matrix tested: every endpoint tested with each role

---

## Phase 2 — Data Ingestion & Health

### Sprint 6 — MQTT Infrastructure & Topic Router

**Goal:** The backend connects to the MQTT broker and can receive messages in both legacy and new topic formats.

**Deliverables:**
- [x] Mosquitto broker running in Docker Compose with authentication
- [x] Backend: Celery MQTT subscriber worker — subscribes to `fm/mm/+/#` and `that-place/scout/+/#`
- [x] Backend: Topic router — registered pattern matching, extracts (scout_serial, device_serial, message_type, stream_key) from any registered pattern
- [x] Backend: Legacy v1 patterns registered (weatherstation, relays, tbox, admin)
- [x] Backend: New v2 pattern registered
- [x] Backend: Messages from unregistered/unapproved devices logged and discarded
- [x] Backend: `topic_format` auto-detected and updated on Device record
- [x] Backend: Tests — both topic formats parsed correctly, unknown device discarded, topic_format flips on format change

**Definition of Done:**
- MQTT worker starts with `docker-compose up` and connects to broker
- Test message on legacy topic format routed and parsed correctly
- Test message on new topic format routed and parsed correctly
- Message from unregistered serial number discarded and logged

---

### Sprint 7 — Stream Ingestion & Auto-Discovery

**Goal:** Incoming telemetry is stored as StreamReadings; new stream keys automatically create Stream records.

**Deliverables:**
- [x] Backend: Telemetry message handler — creates `StreamReading` for known streams
- [x] Backend: Stream auto-discovery — unknown stream key on approved device creates new `Stream` record with data_type defaulting to `numeric`
- [x] Backend: `RuleStreamIndex` maintained on stream creation (no rules yet, but infrastructure ready)
- [x] Backend: Ingestion pipeline performance test — target < 5s latency from receipt to stored reading
- [x] Backend: Tests — happy path ingestion, stream auto-creation, duplicate reading handling, unapproved device rejected

**Definition of Done:**
- Sending a telemetry MQTT message results in a StreamReading in the database within 5 seconds
- A new stream key auto-creates a Stream record
- An unapproved device's messages are discarded with no data stored

---

### Sprint 8 — Device Health Monitoring

**Goal:** Device health is tracked in real time; offline detection runs automatically.

**Deliverables:**
- [x] Backend: `DeviceHealth` record updated on every received message (last_seen_at, signal, battery, activity_level derived from thresholds)
- [x] Backend: Health topic handler for Scout health messages
- [x] Backend: Celery beat task — checks all active devices against their offline threshold, marks offline when exceeded
- [x] Backend: Per-device threshold override respected
- [x] Backend: Tests — activity_level derivation, offline detection at threshold, override respected
- [x] Frontend: Device list — health status indicator (colour-coded: online/degraded/critical/offline)
- [x] Frontend: Device detail — health tab (battery, signal, last seen, first active, activity level)

**Definition of Done:**
- Devices show correct health status on device list within 30 seconds of status change
- A device with no messages for longer than its threshold is marked offline
- Per-device threshold override overrides device type default

---

### Sprint 9 — Stream Configuration UI

**Goal:** Tenant Admin can configure how streams are labelled and which appear on dashboards.

**Deliverables:**
- [x] Backend: Stream label, unit override PATCH endpoint
- [x] Backend: Stream display enable/disable PATCH endpoint
- [x] Backend: Tests — label/unit updates persist, display flag does not affect data storage
- [x] Frontend: Streams tab on device detail — list all streams with current value, label/unit edit inline, display toggle

**Definition of Done:**
- Tenant Admin can rename streams and set units
- Toggling display off hides a stream from dashboard widgets but data continues to be stored
- Disabled streams still appear in the configuration list (just marked as disabled)

---

### Sprint 10 — 3rd Party API Integration

**Goal:** That Place Admin can add a provider; Tenant Admin can connect their account and have devices auto-discovered.

**Deliverables:**
- [x] Backend: `ThirdPartyAPIProvider` model + CRUD (That Place Admin)
- [x] Backend: `DataSource` + `DataSourceDevice` models
- [x] Backend: Device discovery endpoint — calls provider's discovery endpoint using tenant credentials, returns device list
- [x] Backend: DataSourceDevice connect endpoint — creates virtual Device records for selected devices
- [x] Backend: Celery beat poller — calls detail endpoint per active DataSourceDevice on provider's interval
- [x] Backend: OAuth2 password grant token handling + refresh
- [x] Backend: Poll failure logging, retry with exponential backoff, device health warning on consecutive failures
- [x] Backend: Tests — discovery flow, polling stores StreamReadings, auth failure handled, retry logic
- [x] Frontend: That Place Admin — provider library (create provider, define auth schema, discovery/detail endpoints, available streams)
- [x] Frontend: Tenant Admin — add data source (pick provider → enter credentials → discover devices → select devices → select streams)
- [x] Frontend: DataSource management page (list connected devices, add/remove devices)

**Definition of Done:**
- SoilScouts (or equivalent) provider can be configured by That Place Admin
- Tenant Admin can connect their SoilScouts account, see discovered devices, and select which to activate
- StreamReadings appear in the database within one poll interval of connecting

---

**Phase 2 Sign-Off Checklist:** ✅ Signed off 2026-03-18
- [x] All Sprint 0–10 tests passing (full cumulative suite — no failures, no skips)
- [x] Manual smoke test: register Scout → send MQTT message → verify StreamReading stored → verify device health updated
- [x] Manual smoke test: add 3rd party data source → discover devices → confirm readings stored
- [x] Legacy topic format confirmed working with a test client
- [x] Offline detection confirmed by stopping MQTT messages and waiting for threshold

---

## Phase 3 — Dashboards & Visualisation

### Sprint 11 — Dashboard Foundation & Value Card

**Goal:** Tenant Admin can create dashboards and add value card widgets.

**Deliverables:**
- [x] Backend: `Dashboard` + `DashboardWidget` CRUD endpoints
- [x] Backend: Stream readings endpoint with `?from=&to=&limit=` filtering
- [x] Backend: Tests — dashboard isolation per tenant, widget CRUD, time range filtering
- [x] Frontend: Dashboard list page (create, delete, navigate between dashboards)
- [x] Frontend: Dashboard canvas — fixed grid layout with column selector (1/2/3 cols)
- [x] Frontend: Widget builder modal — stream picker (site → device → stream)
- [x] Frontend: Value card widget — latest reading, trend indicator, time since last update
- [x] Frontend: 30-second auto-refresh

**Definition of Done:**
- Can create a dashboard, set column count, add a value card widget bound to a stream
- Value card shows live data and updates every 30 seconds
- Dashboard is shared across all tenant users — all roles can see it

---

### Sprint 12 — Line Chart & Gauge Widgets

**Goal:** Tenant Admin can add line charts with multiple streams and dual Y-axes, and gauge widgets.

**Deliverables:**
- [x] Frontend: Line chart widget — multiple streams per chart, dual Y-axis support, each stream as a separate line, configurable time range
- [x] Frontend: Gauge widget — single stream, configurable min/max/threshold bands
- [x] Frontend: Time range selector (last hour / 24h / 7d / 30d / custom)
- [x] Frontend: Cross-device stream selection in widget builder

**Definition of Done:**
- Line chart renders multiple streams from different devices on the same chart
- Dual Y-axis works — left and right axis each have independently selected streams
- Gauge reflects current value with correct band colouring
- Time range change reloads chart data

---

### Sprint 13 — Status Indicator & Health/Uptime Chart Widgets

**Goal:** All 5 widget types are complete; dashboard layout is polished.

**Deliverables:**
- [x] Frontend: Status indicator widget — colour/label driven by stream value mapped to device type's status indicator config
- [x] Frontend: Health/uptime chart widget — online/offline history, battery and signal as line charts
- [x] Frontend: Widget drag-to-reorder within grid
- [x] Frontend: Responsive reflow — single column below 1024px
- [x] Frontend: Edit widget — each widget has an edit action (e.g. gear/pencil icon) that re-opens the widget builder modal pre-populated with the widget's current config; saving calls the existing `PUT /api/v1/dashboards/:id/widgets/:widget_id/` endpoint and updates the widget in place without deleting and recreating it

**Definition of Done:**
- All 5 widget types working: line chart, gauge, value card, status indicator, health/uptime chart
- Status indicator correctly maps stream values to colours/labels as configured on device type
- Widgets can be reordered by drag
- Layout reflows correctly on a 768px-wide browser window
- Clicking edit on an existing widget opens the builder modal with current config pre-filled; saving updates the widget without page reload

---

**Phase 3 Sign-Off Checklist:**
- [ ] All Sprint 0–13 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: create dashboard with all 5 widget types, confirm live data updates
- [ ] Cross-device widget confirmed — single line chart showing streams from two different devices
- [ ] Responsive layout confirmed at 768px and 1024px widths

---

## Phase 4 — Rules Engine & Alerts

### Sprint 14 — Rule Data Model & API

**Goal:** Rules can be created, edited, and deleted via API with full data model in place.

**Deliverables:**
- [x] Backend: `Rule`, `RuleConditionGroup`, `RuleCondition`, `RuleAction`, `RuleStreamIndex`, `RuleAuditLog` models
- [x] Backend: Rule CRUD endpoints (Tenant Admin only)
- [x] Backend: `RuleStreamIndex` maintained automatically on rule create/edit/delete
- [x] Backend: `RuleAuditLog` entry created on every rule save (before/after diff)
- [x] Backend: Tests — cross-tenant isolation, Admin-only rule creation, RuleStreamIndex accuracy, audit log immutability

**Definition of Done:**
- Rules can be created with conditions and actions via API
- RuleStreamIndex correctly maps every referenced stream to the rule
- Every save creates an audit log entry with before/after field values
- Tenant B cannot read or modify Tenant A's rules

---

### Sprint 14a — Discovery Device Search & Filter

**Goal:** Tenant Admins can search through large discovery result sets before selecting devices to connect.

**Context:** Providers with large fleets (e.g. 500+ devices) make the flat discovery table unusable without filtering. This is a frontend-only improvement — the backend `POST /api/v1/data-sources/:id/discover/` endpoint already returns the full list in one response; filtering happens client-side.

**Deliverables:**
- [x] Frontend: Search input rendered above the device table in `WizardStep2` after discovery completes — filters by device name or external ID (case-insensitive, partial match)
- [x] Frontend: "Select all" checkbox applies only to visible (filtered) non-connected devices
- [x] Frontend: Selection count label reflects filtered view ("Showing X of Y — Z selected")
- [x] Frontend: Existing per-device selections are preserved when the search term changes (deselecting a filter reveals previously selected devices with their state intact)
- [x] Frontend: Same search behaviour applied to the `AddDevicesFlow` (re-discovery on an existing DataSource)

**Definition of Done:**
- With 500 discovered devices, typing in the search box filters the table in real time with no lag
- "Select all" with an active filter selects only filtered devices; clearing the filter shows all devices with their correct selected state
- The count label stays accurate as the filter and selections change
- No backend changes — existing tests continue to pass with no modifications

---

### Sprint 15 — Rule Builder Frontend

**Goal:** Tenant Admin can build a complete rule using the visual step-flow interface.

**Deliverables:**
- [x] Frontend: Rule list page (list, enable/disable toggle, delete)
- [x] Frontend: Rule builder — step flow (name/description → schedule gate → conditions → actions → review & save)
- [x] Frontend: Schedule gate step — day multi-select (with Weekdays/Weekends/Every day shortcuts) + optional time window
- [x] Frontend: Condition builder — add/remove groups, AND/OR per group, top-level AND/OR, stream picker (site → device → stream), operator dropdown filtered by stream data type, value input adapts to type (number/toggle/text)
- [x] Frontend: Staleness condition option — select stream + enter threshold
- [x] Frontend: Action builder — notification action (channels + groups/users + message template with variable hints), device command action (device + command picker, param form)
- [x] Frontend: Review step — summary of all conditions and actions before saving
- [x] Frontend: Rule detail page with audit trail tab

**Definition of Done:**
- Can build and save a complete rule with multiple condition groups and multiple actions
- Operator dropdown shows only valid operators for the selected stream's data type
- Schedule gate saves correctly and is reflected in review step
- Audit trail tab shows all historical changes with before/after values

---

### Sprint 15a — Feed Providers & Reference Datasets

**Goal:** That Place Admin can configure API-polled data feeds and admin-managed lookup tables; both are available as rule condition sources in the rule builder and evaluation engine.

**Context:** This sprint must be complete before Sprint 16 (Rule Evaluation Engine) — the evaluator needs to handle `feed_channel` and `reference_value` condition types. The rule builder frontend (Sprint 15) should have stub pickers for these condition types that are fully wired up once this sprint is complete.

**Deliverables:**

_Backend — Feed Providers:_
- [x] `FeedProvider`, `FeedChannel`, `FeedReading`, `TenantFeedSubscription`, `FeedChannelRuleIndex` models + migrations
- [x] `FeedProvider` CRUD endpoints (That Place Admin only)
- [x] `FeedChannel` records auto-populated from endpoint channel config on provider create/update; dimension values discovered and created on first successful poll
- [x] Celery beat task: polls each active `scope=system` FeedProvider on its configured interval; iterates `response_root_jsonpath`, extracts dimension + channel values via JSONPath, stores `FeedReading` records (idempotent — duplicate `(channel_id, timestamp)` silently ignored)
- [x] On new `FeedReading`, dispatch rule evaluation for rules in `FeedChannelRuleIndex` for that channel
- [x] `TenantFeedSubscription` model + endpoints (for `scope=tenant` providers); Celery beat task polls active subscriptions
- [x] Poll failure logging; platform notification to That Place Admins after 3 consecutive failures
- [x] `FeedChannelRuleIndex` maintained on rule create/edit/delete (alongside existing `RuleStreamIndex`)
- [x] New `RuleCondition.condition_type = feed_channel`: evaluated against latest `FeedReading`; numeric operators only
- [x] AEMO NEM `FeedProvider` seeded on first deployment (see `docs/providers/aemo-nem.md`)
- [x] Tests: feed polling stores readings (idempotent), FeedChannelRuleIndex accurate, feed condition evaluates correctly, poll failure logged, cross-tenant isolation on subscription endpoints

_Backend — Reference Datasets:_
- [x] `ReferenceDataset`, `ReferenceDatasetRow`, `TenantDatasetAssignment` models + migrations
- [x] `ReferenceDataset` CRUD + row CRUD endpoints (That Place Admin only)
- [x] `TenantDatasetAssignment` CRUD endpoints (Tenant Admin; filtered by tenant)
- [x] `/resolve/` endpoint on assignment — returns current row(s) that would be used in evaluation (preview)
- [x] Row resolution logic: dimension filter match → version selection (pinned or latest active) → TOU filter in tenant timezone → return `values`; raise error if multiple rows match (misconfiguration guard)
- [x] New `RuleCondition.condition_type = reference_value`: resolved at evaluation time via assignment; Celery beat task re-evaluates rules with reference_value-only conditions every 5 minutes
- [x] `network-tariffs` dataset seeded via Django fixture (`backend/apps/feeds/fixtures/network_tariffs_2025_26.json`) — all 8 NEM DNSPs (Ausgrid, Endeavour Energy, Essential Energy, Energex, Ergon Energy, Evoenergy, SA Power Networks, TasNetworks), all published tariff codes, all TOU period rows for financial year 2025-26; rates sourced from each DNSP's published network pricing schedule (see `docs/providers/` for source links)
- [x] `co2-emission-factors` dataset seeded via fixture (`backend/apps/feeds/fixtures/co2_emission_factors.json`) — standard Australian grid emission factors by energy source (grid electricity, natural gas, diesel, LPG) sourced from Australian Government National Greenhouse Accounts
- [x] Row bulk import: That Place Admin can upload a CSV to `POST /api/v1/reference-datasets/:id/rows/bulk/` — CSV columns match the dataset's dimension schema + value schema fields + optional version/applicable_days/time_from/time_to; rows are upserted (matched on dimensions + version, updated if exists, created if not); import errors returned per row with row number and reason
- [x] Annual update workflow: adding a new financial year's rates requires only uploading a new CSV with `version: "2026-27"` — existing rows are untouched; tenants with `version: null` assignments automatically resolve to the new version from their effective date
- [x] Tests: row resolution (flat, versioned, TOU in tenant timezone), assignment override for site vs tenant-wide, reference_value condition evaluates correctly, beat task re-evaluates on schedule, bulk import upserts correctly, bulk import returns per-row errors on bad data, Tenant B cannot read Tenant A's assignments

_Frontend:_
- [x] That Place Admin: Feed Provider management page — create/edit provider (name, base URL, auth type, scope, poll interval, endpoint builder with channel rows)
- [x] That Place Admin: Reference Dataset management page — create/edit dataset (schema builder for dimension + value columns, TOU and version toggles), manage rows (table with inline add/edit/delete, version filter)
- [x] Tenant Admin: Feed Subscriptions page — lists `scope=tenant` providers, subscribe/unsubscribe, select channels
- [x] Tenant Admin: Dataset Assignments page (accessible per site from site settings) — assign a dataset, enter dimension filter, pin version or use latest, set effective dates; preview resolved row(s) via `/resolve/` endpoint
- [x] Rule builder condition builder: feed channel picker (provider → dimension value → channel, with current reading shown as preview); reference value picker (dataset → value key, with resolved current value shown as preview)

**Definition of Done:**
- AEMO NEM spot prices are stored as `FeedReading` records every 5 minutes
- A rule with condition "AEMO NSW1 spot price > 300 $/MWh" evaluates correctly and fires when the threshold is crossed
- A `network-tariffs` dataset assignment can be created for a site; `/resolve/` returns the correct rate for the current time of day
- A `reference_value` condition resolves to the correct rate in tenant timezone (peak vs off-peak)
- Celery beat task re-evaluates reference_value-only rules every 5 minutes
- All new endpoints pass cross-tenant isolation tests
- Rule builder shows feed channel and reference value pickers with live previews

---

### Sprint 16 — Rule Evaluation Engine

**Goal:** Rules evaluate automatically when qualifying readings arrive; firing is correct and race-condition safe.

**Deliverables:**
- [x] Backend: Celery task dispatched on StreamReading save — looks up rules via `RuleStreamIndex`, evaluates each
- [x] Backend: Celery task dispatched on FeedReading save — looks up rules via `FeedChannelRuleIndex`, evaluates each (Sprint 15a must be complete)
- [x] Backend: Schedule gate evaluation (day of week + time window in tenant timezone)
- [x] Backend: Point-in-time condition evaluation (numeric/boolean/string operators) — stream, feed_channel, and reference_value condition types all supported
- [x] Backend: Compound condition group evaluation (AND/OR per group, top-level AND/OR)
- [x] Backend: Re-triggering suppression — fire only on false→true transition
- [x] Backend: Redis atomic flag (`SET rule:{id}:state NX`) for concurrency safety
- [x] Backend: Cooldown logic — respect `cooldown_minutes` before re-firing after condition clears
- [x] Backend: `Rule.current_state` and `last_fired_at` updated on every evaluation
- [x] Backend: Tests — false→true fires, true→true suppressed, true→false clears state, cooldown respected, concurrent evaluation race condition test, feed_channel condition fires on new FeedReading, reference_value condition resolves correctly

**Definition of Done:**
- A rule with `temp > 30` fires exactly once when temperature crosses 30
- Stays suppressed while temperature remains above 30
- Fires again after temperature drops below 30 and rises above again
- Two simultaneous readings do not cause duplicate firing (Redis flag test)
- Schedule gate prevents firing outside the configured window
- A rule with a feed_channel condition fires when a new FeedReading crosses the threshold
- A rule mixing stream and reference_value conditions evaluates both correctly

---

### Sprint 17 — Staleness Conditions & Rule Polish

**Goal:** Staleness conditions work; rule engine handles all edge cases.

**Deliverables:**
- [x] Backend: Celery beat task (60s interval) — evaluates all active staleness conditions across all tenants
- [x] Backend: Staleness condition fires when stream has not reported within `staleness_minutes`
- [x] Backend: Staleness condition clears when stream reports again
- [x] Backend: Minimum staleness threshold enforcement (2 minutes minimum)
- [x] Backend: Tests — staleness fires after threshold, clears on new reading, 2min minimum enforced
- [x] Frontend: Rule list page shows last fired time and current state badge
- [x] Frontend: Rule detail shows current state, last fired, next earliest fire (if cooldown active)

**Definition of Done:**
- A staleness condition fires within 60 seconds of the threshold being exceeded
- Clears automatically when the stream reports again
- Configuring a threshold below 2 minutes returns a validation error

---

### Sprint 18 — Alerts

**Goal:** Rule firings create alerts; operators can manage alert status.

**Deliverables:**
- [x] Backend: `Alert` record created atomically with rule firing (same Celery task as evaluation)
- [x] Backend: Alert acknowledge endpoint (Admin + Operator) — accepts optional `acknowledged_note`
- [x] Backend: Alert resolve endpoint (Admin + Operator)
- [x] Backend: Alert list endpoint — active alerts and history, filterable by site/device/rule/status
- [x] Backend: Tests — alert created on fire, duplicate alert prevention (one active per rule), acknowledge/resolve transitions, View-Only cannot acknowledge
- [x] Frontend: Alert feed — active alert view (what is wrong right now)
- [x] Frontend: Alert history tab — all past firings, filterable
- [x] Frontend: Alert detail — rule name, triggered at, device/site, acknowledge action (single tap + optional note field), resolve action
- [x] Frontend: Alert badge in navigation (count of active alerts)

**Definition of Done:**
- Rule firing creates exactly one Alert record
- Active alert feed shows only current unresolved issues
- Acknowledging an alert with a note saves correctly
- View-Only user sees alerts but acknowledge/resolve buttons are hidden/disabled
- Alert badge updates within 30 seconds of a new alert

---

**Phase 4 Sign-Off Checklist:**
- [ ] All Sprint 0–18 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: build a rule → trigger condition → confirm alert created → acknowledge → resolve
- [ ] Staleness rule confirmed: disconnect device, wait for threshold, confirm alert fires
- [ ] Concurrent evaluation test: send 10 rapid readings, confirm rule fires exactly once
- [ ] Schedule gate confirmed: rule does not fire outside configured time window

---

## Phase 5 — Notifications, Control & Export

### Sprint 19 — In-App Notifications & System Events

**Goal:** Users receive in-app notifications for alerts and system events.

**Deliverables:**
- [x] Backend: `Notification` model — supports both alert-triggered and system event types
- [x] Backend: In-app notification creation on alert fire (per targeted user)
- [x] Backend: System event notifications: device approved, device offline, device deleted, DataSource poll failure
- [x] Backend: Unread count endpoint
- [x] Backend: Mark as read endpoint (individual notification)
- [x] Backend: Mark all as read endpoint (bulk — marks every unread notification for the user as read)
- [x] Backend: Tests — notification created per targeted user, system events generate notifications, unread count accurate, mark-all-as-read clears badge
- [x] Frontend: Notification bell in nav with unread badge
- [x] Frontend: Notification dropdown/panel — list with unread indicators, tap to navigate to related alert
- [x] Frontend: Tapping a notification marks it as read and navigates to the related alert
- [x] Frontend: "Mark all as read" button in notification panel header

**Definition of Done:**
- Alert fire generates in-app notifications for all targeted users
- Device going offline generates a system notification
- Unread badge count is accurate
- Tapping a notification marks it read and navigates to the relevant alert
- "Mark all as read" clears the unread badge and all unread indicators

---

### Sprint 19a — Widget Titles

**Goal:** Every dashboard widget displays an editable title that defaults to the names of its bound devices.

**Deliverables:**
- [x] Backend: `title` field added to all widget config JSONB schemas; serializer validates it is non-blank and ≤ 120 characters
- [x] Frontend: Widget builder modal — title field pre-populated with auto-generated device-name default for new widgets; editable for existing widgets
- [x] Frontend: Auto-title logic — 1 device → `"<Device Name>"`; 2 devices → `"<Device A> & <Device B>"`; 3+ devices → `"<Device A>, <Device B> + N more"` — computed at widget-creation time and saved into config
- [x] Frontend: Widget card — title rendered at the top of every widget; Tenant Admin / Operator can click the title to edit it inline (text input; blur or Enter saves via PUT)
- [x] Frontend: Inline title edit saves via the existing `PUT /api/v1/dashboards/:id/widgets/:widget_id/` endpoint; optimistic update with rollback on error
- [x] Frontend: View-Only users see the title but cannot edit it (click is a no-op)

**Definition of Done:**
- New widgets default to a device-name-based title visible on the card
- Inline title edit persists on blur/Enter and rolls back on API error
- Title is shown in all widget types (line chart, gauge, value card, status indicator, health chart)
- View-Only users cannot trigger the inline edit
- Blank title is rejected by the backend (400) and the frontend does not save it

---

### Sprint 20 — Email, SMS & Notification Snooze

**Goal:** Users receive email and SMS notifications on alert fire; opt-out and snooze are respected.

**Deliverables:**
- [x] Backend: Email delivery via configured SMTP backend (AWS SES or any SMTP provider — set via `EMAIL_*` env vars)
- [x] Backend: SMS delivery via chosen provider
- [x] Backend: Per-channel user preferences — in-app and email on by default, SMS off by default (opt-in)
- [x] Backend: SMS blocked at delivery if user has not opted in, regardless of rule action channels
- [x] Backend: Delivery failure logging and single retry
- [x] Backend: User notification preferences endpoint
- [x] Backend: `NotificationSnooze` model — user + rule + snoozed_until; unique per (user, rule)
- [x] Backend: Snooze endpoint — POST /api/v1/notifications/snooze/ with rule_id and duration_minutes
- [x] Backend: Cancel snooze endpoint — DELETE /api/v1/notifications/snooze/:rule_id/
- [x] Backend: Snooze check in `create_alert_notifications` — skip writing notification for any user with an active snooze on that rule
- [x] Backend: Tests — email sent to targeted users, SMS not sent to non-opted-in user, opted-out user not emailed, snoozed user receives no notification during snooze window, snooze expiry restores delivery
- [x] Frontend: User profile / notification preferences page — email/in-app toggles (default on), SMS toggle (default off, with explanation that SMS must be explicitly enabled)
- [x] Frontend: Snooze button on notification panel items — duration picker (15 min / 1 hour / 4 hours / 24 hours)
- [x] Frontend: Snoozed indicator in notification panel (clock icon + expiry time) with cancel option

**Definition of Done:**
- Alert fires trigger in-app and email to targeted users by default
- SMS only sent to users who have explicitly opted in
- A user who has opted out of email does not receive email notifications
- A user who has snoozed a rule receives no new notifications for that rule until the snooze expires
- Snooze expiry is automatic — user receives notifications again when snoozed_until passes
- Failed deliveries are logged with error detail and retried once

---

### Sprint 21 — Device Commands

**Goal:** Admin and Operator can send commands to devices; commands are logged and ack tracked. Rule-triggered commands are dispatched automatically on rule fire.

**Deliverables:**
- [x] Backend: mTLS MQTT publish capability — `ThatPlaceMQTTClient` extended with `publish(topic, payload, qos=1)` method; connects on port 8883 using `MQTT_BACKEND_CERT_B64` / `MQTT_BACKEND_KEY_B64`; Docker Compose stack generates self-signed CA and backend client cert on first start
- [x] Backend: `CommandLog` model (device, sent_by nullable, triggered_by_rule nullable, command_name, params_sent, sent_at, ack_received_at, status)
- [x] Backend: `devices.send_device_command` Celery task — resolves Scout serial from device `gateway_device` (or device own serial), constructs MQTT topic (`that-place/scout/…/cmd/{command_name}`), publishes params as JSON, creates `CommandLog` with status `sent`; new-format (`that_place_v1`) devices only
- [x] Backend: Command send endpoint (`POST /api/v1/devices/:id/command/`) — validates command name and params against device type `commands` JSONB definition, dispatches Celery task; Admin + Operator only
- [x] Backend: MQTT ack listener — ingestion router handles `cmd/ack` topic; parses `command` field from payload JSON; matches to most-recent `sent` `CommandLog` for that device with matching `command_name`; sets status `acknowledged` and `ack_received_at`; logs warning and discards if no match
- [x] Backend: Timeout detection Celery beat task — every 60 seconds marks `CommandLog` entries with status `sent` and `sent_at` older than `device_type.command_ack_timeout_seconds` as `timed_out`
- [x] Backend: Command history endpoint (`GET /api/v1/devices/:id/commands/`) — Admin + Operator only
- [x] Backend: Rule evaluation task updated — when a `RuleAction` with `action_type=command` fires, dispatches `devices.send_device_command` with `triggered_by_rule` set and `sent_by=None`
- [x] Backend: Tests — command validated against device type (invalid command name rejected, missing required param rejected), ack received updates log, ack with unknown command discarded, timeout fires correctly, View-Only blocked, rule-triggered command creates CommandLog with correct fields, cross-tenant command send rejected
- [x] Frontend: Send command button on device detail (Admin + Operator only)
- [x] Frontend: Command picker — shows commands registered for this device type
- [x] Frontend: Command param form — auto-generated from param schema (number input, toggle, text field per param type)
- [x] Frontend: Command history tab on device detail

**Definition of Done:**
- Can send a command from the UI — appears in command history with status `sent`
- Mock ack received with correct `command` field — status updates to `acknowledged`
- No ack within timeout period — status updates to `timed_out`
- View-Only user cannot see the send command button
- Rule firing with a command action creates a `CommandLog` entry with `triggered_by_rule` set
- mTLS connection confirmed: backend connects to broker on port 8883 with client certificate

---

### Sprint 21a — 3rd Party API Provider Commands _(Deferred)_

> **Deferred to a later phase** — no virtual devices currently require this infrastructure. Revisit when a provider with control capability is onboarded.

**Goal:** Extend the command infrastructure built in Sprint 21 to support control actions on virtual (3rd party API) devices. Provider commands are HTTP calls to the provider API — not MQTT — but share the same param schema, command picker UI, and `CommandLog` for history.

**Deliverables:**
- [ ] Backend: `commands` JSONB field added to `ThirdPartyAPIProvider` — same schema as `DeviceType.commands` plus `endpoint` and `method` per entry; That Place Admin can configure per provider
- [ ] Backend: Command send endpoint extended — detects whether the target device is virtual; if so, dispatches an authenticated HTTP call to the provider API (using the DataSource credentials) instead of an MQTT publish; params substituted into the endpoint path and/or request body
- [ ] Backend: `CommandLog` records created the same way as MQTT commands; no `ack_received_at` (HTTP commands are synchronous — a 2xx response = acknowledged, non-2xx = timed_out); status set immediately on response
- [ ] Backend: Tests — virtual device command dispatched as HTTP not MQTT, 2xx sets acknowledged, non-2xx sets timed_out, View-Only blocked, MQTT device path unchanged
- [ ] Frontend: Command picker on virtual device detail shows provider commands (sourced from `ThirdPartyAPIProvider.commands`) using the same auto-generated param form as MQTT device commands
- [ ] Frontend: That Place Admin provider config form — commands JSONB editor (name, label, description, endpoint, method, params array)

**Definition of Done:**
- That Place Admin can add a command to a provider config and save it
- Tenant Admin/Operator sees the command on the virtual device detail and can send it
- Successful call logs as `acknowledged`; failed call logs as `timed_out` with error detail
- MQTT device command path is entirely unaffected
- View-Only user cannot send provider commands

---

### Sprint 22 — CSV Data Export

**Goal:** Admin and Operator can export stream data as a streaming CSV download.

**Deliverables:**
- [x] Backend: `StreamingHttpResponse` CSV export endpoint — queries readings in batches, streams rows to client
- [x] Backend: CSV format: one row per reading (long format), columns: timestamp, site_name, device_name, device_id, device_serial, stream_label, value, unit
- [x] Backend: `DataExport` log entry created before streaming begins (captures intent even on client disconnect)
- [x] Backend: Export history endpoint (Admin only)
- [x] Backend: Tests — CSV format correct, multi-stream export correct, streaming response confirmed, View-Only blocked, cross-tenant streams rejected, non-Admin cannot view history
- [x] Frontend: "Reporting" nav item (Admin + Operator only) with Export and History tabs
- [x] Frontend: Export tab — date/time range pickers (from exclusive, to inclusive) + cross-device stream picker (expand per device, checkbox per stream)
- [x] Frontend: Download CSV button — triggers streaming blob download via Axios
- [x] Frontend: Export history tab (Admin only) — table of past exports with exporter email, stream count, date range

**Definition of Done:**
- Export with 3 streams over 30 days downloads as a single correctly formatted CSV
- Large exports do not timeout (streaming confirmed)
- Export history shows correct metadata
- Operator can export but cannot see history

---

### Sprint 23 — That Place Admin Notifications & Platform Events

**Goal:** That Place Admins receive notifications for platform-level events.

**Deliverables:**
- [ ] Backend: That Place Admin notification generation for: pending device approvals, MQTT broker connectivity failures, 3rd party API provider failures affecting multiple tenants
- [ ] Backend: Notification event registry — centralised registration of event types (not hardcoded)
- [ ] Backend: Tests — each platform event generates correct notifications, only That Place Admins receive them
- [ ] Frontend: That Place Admin notification panel (separate from tenant user notifications)

**Definition of Done:**
- Pending device creates a notification for all That Place Admins
- MQTT connectivity failure creates a platform notification
- Notification event registry allows new event types to be added without code changes to the dispatch layer

---

### Sprint 24 — Push Notifications

**Goal:** Mobile push notifications delivered via Expo Push Service (in preparation for Phase 6 mobile app, but infrastructure built now).

**Deliverables:**
- [ ] Backend: Expo push token storage on user profile
- [ ] Backend: Push notification delivery on alert fire (alongside in-app/email/SMS)
- [ ] Backend: Tests — push token stored, push dispatched on alert fire

**Definition of Done:**
- Push notification infrastructure in place and tested
- Ready to be consumed by Phase 6 React Native app with no backend changes

---

### Sprint 25 — Integration Testing & Phase 1–5 Sign-Off

**Goal:** All features work end-to-end; the platform is stable and ready for Phase 6.

**Deliverables:**
- [ ] End-to-end tests (Playwright) for key user journeys:
  - Onboarding: create tenant → invite admin → set up site → register device → approve device
  - Ingestion: send MQTT reading → verify StreamReading → verify health update
  - Rules: build rule → trigger condition → alert fires → in-app notification received → acknowledge alert
  - Commands: send command → ack received → history logged
  - Export: configure export → download CSV → verify format
- [ ] Performance audit: identify and fix any N+1 queries, slow endpoints (> 500ms on realistic data)
- [ ] Security audit: cross-tenant isolation, auth bypass attempts, View-Only access checks
- [ ] Bug fix sprint — address all issues found during E2E and audits

**Definition of Done:**
- All Playwright E2E tests pass
- No endpoint returns data from another tenant under any circumstances
- No endpoint exceeds 500ms on a dataset of 100k StreamReadings
- All known bugs resolved or explicitly deferred with rationale

---

**Phases 1–5 Final Sign-Off:**
- [ ] All Sprint 0–25 complete with passing tests (full cumulative suite — no failures, no skips)
- [ ] E2E tests passing
- [ ] No open P1 or P2 bugs
- [ ] SPEC.md and ERD.md up to date with any changes made during development

---

## Phase 6 — React Native Mobile App

> Plan this phase in detail when Phase 1–5 sign-off is complete.

**High-level scope:**
- React Native (Expo) app targeting iOS and Android
- Key screens: dashboard viewer, device list + detail, alert feed, acknowledge alert, send command
- Push notifications via Expo Push Service (backend already built in Sprint 24)
- Offline: cached dashboard view, graceful degradation

---

## Phase 7 — Polish & Scale

> Plan when Phase 6 is complete.

- Real-time WebSocket push (replace polling)
- PDF report builder
- Downsampled historical data for long-term charts
- Performance: CDN, read replicas, query optimisation
- Per-user dashboards
- Data sovereignty configuration

---

## Phase 8 — Future

> Requires separate planning and discussion.

- Runner device support (offline rule execution at the edge)
- ML/AI rule conditions
- Rule approval workflows
- Alert escalation policies
- Scheduled data exports
