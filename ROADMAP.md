# That Place — Development Roadmap

> Reflects SPEC.md v5.3. Sprints are sequenced as vertical slices — each sprint delivers
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

**Goal:** That Place Admins receive notifications for platform-level events, dispatched through a configurable event registry.

**Pre-sprint deep dive — ✅ resolved 2026-05-20** (closes SPEC.md §9 ⚑ "Notification event registry" and ⚑ "That Place Admin notification channel"):
- **Delivery channels:** in-app + email for v1 — email reuses the Sprint 20 SMTP backend. Outbound webhook delivery (Slack / PagerDuty / ops tooling) is flagged for future development — see Backlog.
- **Event registry:** DB-backed configurable model. A `NotificationEventType` record per event type carries key, label, description, severity, audience, default channels, metadata schema, and an editable message template. New event types are added as data; only the code that *detects* a condition and emits the event is code-level.
- **Event list (v1):** pending device approval, MQTT broker connectivity failure, multi-tenant 3rd-party API provider failure, feed provider poll failure (consolidates the Sprint 15a notification), tenant lifecycle (created / deactivated), certificate / credential expiry (MQTT backend cert + device certs), backend pipeline failure (Celery worker / ingestion errors).
- **Admin panel:** full parity with the Sprint 19 tenant notification panel — unread badge, read/unread state, mark-all-read, click-to-navigate.

**Deliverables:**

_Backend:_
- [x] `NotificationEventType` model + migration — key, label, description, severity (info/warning/critical), audience (platform_admin/tenant), default_channels (array: in_app/email), metadata_schema (JSONB), message_template, is_active
- [x] `NotificationEventType` CRUD endpoints (That Place Admin only); v1 event types seeded via a `post_migrate` handler (works under the `--no-migrations` test runner, unlike a data migration)
- [x] Central dispatch helper — `emit_event(event_key, metadata, tenant_id)` resolves the registry entry, renders the template, and creates `Notification` records for the resolved recipients on each enabled channel
- [x] Retrofit existing system-event notifications onto the registry — Sprint 19 device events and the Sprint 15a feed-poll-failure notification — no parallel notification paths
- [x] Platform-event emitters (view-detected): pending device approval, feed provider poll failure, tenant created / deactivated
- [x] Platform-event emitters (infrastructure-detected): MQTT broker connectivity failure (paho `on_disconnect`, cooldown-suppressed); third-party API provider-wide outage (every active data source for the provider in `error` / `auth_failure`, cooldown-suppressed per provider); certificate expiry (daily Celery beat — MQTT backend cert + all device mTLS certs, warn at 30 / 14 / 7 days); backend pipeline failure (Celery `task_failure` signal, deduped per task / hour)
- [x] Email delivery of platform notifications via the Sprint 20 SMTP backend
- [x] Tests — registry rendering, audience resolution, channel fan-out, retrofit, all seven emitters, CRUD permissions (29 Sprint 23 tests; full backend + frontend suites green)

_Frontend:_
- [x] That Place Admin notification panel — mirrors the Sprint 19 tenant panel (unread badge, read/unread, mark-all-read, click-to-navigate to the relevant record)
- [x] That Place Admin `NotificationEventType` management page — list, edit severity / channels / message template, enable/disable

**Definition of Done:**
- A pending device creates an in-app + email notification for all That Place Admins
- MQTT broker connectivity loss creates a platform notification
- A new event type can be added — and its template / severity / channels edited — with no code change to the dispatch layer (only a condition-detecting emitter needs code)
- The Sprint 19 tenant system events and the Sprint 15a feed-poll-failure notification flow through the registry — no duplicate paths remain
- The That Place Admin panel has unread/read state, mark-all-read, and navigation parity with the tenant panel
- A certificate / credential expiry warning fires ahead of expiry

> **Status (2026-05-22):** ✅ Complete. Registry, dispatch, retrofit, CRUD, all seven
> platform emitters (3 view-detected + 4 infrastructure-detected), and both frontend
> surfaces are implemented and tested — 670 backend + 43 frontend tests green.

---

### Sprint 23b — That Place Admin Hardening

**Goal:** Close three gaps surfaced while reviewing the That Place Admin console —
protect in-use Reference Datasets from deletion, give the Admin per-tenant user
visibility, and guard against duplicate-email invites across tenants.

**Context:** All three are flagged items in SPEC.md §9. The duplicate-email guard here
is an interim safety net — the full fix (one login spanning multiple tenants) is the
separate **Multi-Tenant User Accounts** sprint (see Backlog), which would supersede it.

**Deliverables:**

_Backend:_
- [x] Reference Dataset delete guard — `DELETE /api/v1/reference-datasets/:id/` returns **409** listing the affected tenants/sites when any `TenantDatasetAssignment` references the dataset (the `dataset` FK is already `on_delete=PROTECT`; the guard surfaces it as a clean 409); the delete proceeds only when none exist
- [x] `GET /api/v1/tenants/:id/users/` — That Place Admin only; returns the tenant's `TenantUser`s (email, role, joined date) plus outstanding unexpired `TenantInvite`s (email, role, invited date, expiry); read-only
- [x] Duplicate-email invite guard — both invite endpoints (`POST /api/v1/tenants/:id/invite/`, `POST /api/v1/users/invite/`) reject with a clear error when the email already belongs to a `TenantUser` in another tenant, or has an active invite elsewhere
- [x] Accept-invite integrity guard — the accept-invite flow rejects with a clear error if the email gained a tenant membership after the invite was sent (backstop for the one-tenant-per-user rule)
- [x] Tests — delete blocked with 409 when in use and allowed when not; tenant-users endpoint scoping (That Place Admin only, cross-tenant denied); duplicate invite rejected at creation; acceptance guard rejects

_Frontend:_
- [x] Reference Datasets page — surface the 409 on delete by naming the tenants/sites still using the dataset, instead of a generic error
- [x] That Place Admin Tenant detail — a read-only "Users" section listing members and pending invites
- [x] Invite forms (tenant-detail invite and tenant-user invite) — show the duplicate-email rejection message clearly

**Definition of Done:**
- Deleting an in-use Reference Dataset is blocked with a 409 that names the dependent tenants/sites; deleting an unused one still works
- A That Place Admin can open any tenant and see its members and pending invites
- Inviting an email that already belongs to another tenant is rejected with a clear message at invite time; acceptance is guarded as a backstop
- All new endpoints pass cross-tenant / permission tests; full backend + frontend suites green

> **Status (2026-05-22):** ✅ Complete. 12 Sprint 23b tests; full backend suite (683)
> and frontend suite (43) green; flake8 / isort / eslint clean.

---

### Sprint 24 — Push Notifications

**Goal:** Mobile push notifications delivered via Expo Push Service (in preparation for Phase 6 mobile app, but infrastructure built now).

**Pre-sprint deep dive — ✅ resolved 2026-05-24:**
- **Token storage:** per-device `UserPushToken` model (one user → many tokens) — matches Expo's per-device token model and lets a user use the platform on more than one device.
- **Opt-in:** no separate `push_enabled` toggle — token presence is the user's consent (the OS-level permission grant already gated registration). To stop push, the user unregisters in-app or revokes OS permission.
- **Delivery tracking:** send-and-forget — `Notification.delivery_status` is set from the immediate per-message ticket returned by Expo (`ok` → delivered, `error` → failed). No receipt polling. Stale `DeviceNotRegistered` tokens are removed.

**Deliverables:**
- [x] Backend: `UserPushToken` model + migration — per-device tokens, unique on token value
- [x] Backend: `/api/v1/notifications/push-tokens/` CRUD — list / register (upsert) / delete; scoped to `request.user`; ownership reassigned on re-registration from a different user
- [x] Backend: `create_alert_notifications` push fan-out — one push `Notification` per user with a registered token, dispatched via `send_push_notification`
- [x] Backend: `send_push_notification` — batched POST to the Expo Push Service; sets `delivery_status` from the per-message ticket; removes `DeviceNotRegistered` tokens
- [x] Backend: Tests — token CRUD + cross-user scoping; alert fire creates push only when tokens exist; Expo `ok` → delivered, `DeviceNotRegistered` → token removed

**Definition of Done:**
- Push notification infrastructure in place and tested
- Ready to be consumed by Phase 6 React Native app with no backend changes

> **Status (2026-05-24):** ✅ Complete. 11 Sprint 24 tests + full backend suite green;
> flake8 / isort clean. Mobile app (Phase 6) consumes `/api/v1/notifications/push-tokens/`
> for registration; push fires automatically on alert when a token exists.

---

### Sprint 25 — Integration Testing & Phase 1–5 Sign-Off

**Goal:** All features work end-to-end; the platform is stable and ready for Phase 6.

**Deliverables:**
- [x] End-to-end tests (Playwright, Chromium + Firefox) for key user journeys:
  - [x] Onboarding: create tenant → invite admin → set up site → register device → approve device
  - [x] Ingestion: send MQTT reading → verify StreamReading → verify health update
  - [x] Rules: build rule → trigger condition → alert fires → in-app notification received → acknowledge alert
  - [x] Commands: send command → ack received → history logged
  - [x] Export: configure export → download CSV → verify format
- [x] Performance audit: confirmed no N+1 queries (4–5 queries per endpoint) and all hot endpoints < 100ms on a 100k-reading dataset (target was 500ms)
- [x] Security audit: cross-tenant probes (404), role matrix (Admin/Operator/Viewer/anon/forged JWT) all enforced
- [x] Bug fix sprint:
  - **Sprint 21 follow-up** — `that-place/scout/{serial}/cmd/ack` (Scout-direct) wasn't registered in `apps/ingestion/router.py`; only the bridged 2-segment form matched. Surfaced by the commands E2E spec; new pattern `that_place_v1_scout_cmd_ack` added with regression test in `apps/ingestion/tests/test_router.py`.

**Definition of Done:**
- [x] All Playwright E2E tests pass (14 tests across Chromium + Firefox)
- [x] No endpoint returns data from another tenant under any circumstances (404 across the probe matrix)
- [x] No endpoint exceeds 500ms on a dataset of 100k StreamReadings — measured 16–64ms across the hot list
- [x] All known bugs resolved or explicitly deferred with rationale

> **Status (2026-05-27):** ✅ Complete. New `/e2e` Playwright suite (5 sign-off journeys + smoke,
> Chromium + Firefox); two new management commands (`seed_e2e`, `seed_perf_data`); one
> Sprint 21 router bug fixed with regression test. Full backend + frontend suites green;
> flake8 / isort / eslint clean.

---

**Phases 1–5 Final Sign-Off:**
- [ ] All Sprint 0–25 complete with passing tests (full cumulative suite — no failures, no skips)
- [ ] E2E tests passing
- [ ] No open P1 or P2 bugs
- [ ] SPEC.md and ERD.md up to date with any changes made during development

---

## Phase 5b — Notification Enhancements

### Sprint 26 — Per-Rule Per-Channel Notification Opt-Out

**Goal:** Users can opt out of specific channels for specific rules, on top of the global per-channel preferences from Sprint 20.

**Deliverables:**
- [x] Backend: `RuleNotificationOptOut` model (user + rule + channel, unique together) + migration `0005_rulenotificationoptout`
- [x] Backend: `GET / PUT /api/v1/rules/:id/my-notification-prefs/` — returns/accepts `{in_app, email, sms, push}` for the requesting user; 403 if user is not currently a target of any notify action on the rule
- [x] Backend: opt-out check in `create_alert_notifications` — most-restrictive wins across global pref, SMS opt-in, push token presence, snooze, and per-rule opt-out
- [x] Backend: 15 new tests in `apps/notifications/tests/test_sprint26.py` covering all four channels, precedence with snooze + global prefs + SMS opt-in, per-user scoping, group-targeted users, cross-tenant 404, operator + viewer access, anonymous block, GET defaults, PUT round-trip
- [x] Frontend: `MyNotificationsPanel` on the rule detail page Overview tab; 4 channel toggles loaded from the new endpoint, save on toggle, hides itself when endpoint returns 403
- [x] Frontend: 6 new tests in `MyNotificationsPanel.test.jsx`

**Definition of Done:**
- [x] A user can disable email for one specific rule while keeping email for all others
- [x] Global per-channel preference and per-rule opt-out are both enforced (most-restrictive wins)
- [x] SPEC.md §8 Phase 5b satisfied

> **Status (2026-05-27):** ✅ Complete. 718 backend tests + 49 frontend tests green;
> flake8 / isort / eslint clean.

---

## Phase B — Metering & Billing

> Detailed per-sprint plan locked in on 2026-05-28 at Phase B kickoff. Source of
> truth is SPEC.md v5.3 — §3 (feature sections), §4 (data model), §5 (API),
> §6 (UI/UX), §8 Phase 4c. The arc is 11 sprints across four sub-phases plus one
> mini-sprint (3rd-party API backfill) and one auth-core sprint (Multi-Tenant
> User Accounts). Each sub-phase ships independent value and has its own
> sign-off checklist.
>
> Backlog folding (decided 2026-05-28):
> - Windowed-aggregate rule conditions → folded into Sprint 27 (shares
>   `window_min` / `window_max` implementation).
> - 3rd-party API history / backfill → mini-sprint 29a between B1 and B2.
> - Outbound webhook delivery for platform notifications → folded into
>   Sprint 37 (shares HMAC + retry infra with the consumer webhook system).
> - Multi-Tenant User Accounts → Sprint 38, after Phase B sign-off.
> - Legacy weatherstation / tbox / abb payload parsers → remain parked
>   (hardware-team payload formats still required — see Backlog below).

### Phase B1 — Foundations (Sprints 27–29)

> SPEC.md §3 (Derived / Computed Streams, Interval Aggregation Engine, Data
> Quality Flags, Metering Model — Meter Profiles), §8 Phase 4c · B1.

---

### Sprint 27 — Derived / Computed Streams + Windowed Aggregate Rule Conditions

**Goal:** Tenant Admins can configure derived streams whose values are computed from other streams (`delta`, `sum`, `difference`, `scale`, `window_min` / `window_max`) and write regular `StreamReading` records on a virtual stream. The windowed-aggregate rule condition type (avg / max / min over a rolling window) lands at the same time because it shares the windowed-evaluation implementation.

**Context:** A derived stream is configured once and writes regular `StreamReading` records on a virtual stream. From that point on every consumer treats it as just another stream — same pattern as the `_battery` / `_signal` virtual streams. Adding a derived stream requires no code. The windowed-aggregate rule condition is folded in because the `window_min` / `window_max` formulas already implement the rolling-window evaluation primitive — adding `window_avg` and exposing it as a rule condition is a thin extension.

**Deliverables:**

_Derived streams (SPEC §3 Derived / Computed Streams):_
- [x] Backend: `DerivedStream` model (key, label, unit, formula type, source stream(s), params JSONB, is_active) one-to-one with a virtual `Stream` where `stream_type = derived`
- [x] Backend: `DerivedStreamSourceIndex` (source → derived) maintained on create / edit / delete via Django signals (m2m_changed + post_delete)
- [x] Backend: v1 formula evaluators — `delta` (current − previous, drop negative, honour `max_gap_minutes`), `sum`, `difference`, `scale`, `window_min`, `window_max` — pure functions in `apps/readings/derived.py`
- [x] Backend: Celery task dispatched on source `StreamReading` save — looks up derived streams via `DerivedStreamSourceIndex`, evaluates each; hooked into `_store_stream_readings` alongside rule dispatch
- [x] Backend: Output `StreamReading` worst-quality propagation built into the evaluators (Sprint 28 will wire it through to the storage layer)
- [x] Backend: Idempotency via `update_or_create` on `(stream, timestamp)` — re-running produces identical end state
- [x] Backend: On-demand backfill endpoint (Tenant Admin, date range) — Celery task that upserts without touching out-of-range derived readings
- [x] Backend: Cross-device derived streams live on a per-site virtual `Device` with `is_virtual=True` and the platform-seeded `Site Composite` DeviceType, auto-created on first cross-device use
- [x] Backend: CRUD + backfill endpoints `/api/v1/derived-streams/` (tenant-scoped; Tenant Admin for writes)
- [x] Backend: 20 integration tests in `apps/readings/tests/test_derived_dispatch.py` + 22 evaluator unit tests in `test_derived_evaluators.py` covering formula correctness, index maintenance, dispatch, idempotency, backfill, site composite auto-creation, cross-tenant isolation, role permissions
- [x] Frontend: `DerivedStreamBuilder` component on the device Streams tab — formula picker, source picker (device → stream, multi-select for sum/difference), per-formula params form
- [x] Frontend: "Provenance" column on the Streams table — Raw / Derived badge

_Windowed aggregate rule conditions (SPEC §3 Rules Engine):_
- [x] Backend: `RuleCondition.condition_type = 'windowed_aggregate'` with `aggregate_fn` (`avg` / `min` / `max`), `window_minutes`, `stream`, `operator`, `threshold_value`
- [x] Backend: `_eval_windowed_aggregate_condition` evaluator reusing the `evaluate_window` primitive from `apps/readings/derived.py`
- [x] Backend: 12 tests in `apps/rules/tests/test_sprint27_windowed.py` — avg/min/max correctness over windows, empty window returns False, readings outside the window excluded, serializer validation across the matrix, `RuleStreamIndex` picks up the source stream
- [x] Frontend: Rule builder adds a "Windowed aggregate" condition type with `aggregate_fn` + `window_minutes` + numeric operator + threshold controls; payload + edit-mode round-trip + step-3 validation included

**Definition of Done:**
- [x] Configuring `consumption_from_solar = generation − grid_export` (cross-device `difference`) produces a stream readable like any other; host Device is the auto-created Site Composite
- [x] Configuring `interval_kwh = delta(cumulative_kwh)` produces correct interval values; counter resets drop cleanly; gaps over `max_gap_minutes` produce no reading
- [x] Backfill over a date range recomputes derived history idempotently and does not touch readings outside the window (test_backfill_does_not_touch_readings_outside_range)
- [x] A rule with condition "avg temperature over the last 15 minutes > 25" fires when the rolling average crosses the threshold
- [x] All cross-tenant isolation tests continue to pass

> **Status (2026-05-28):** ✅ Complete. 773 backend tests + 55 frontend tests green
> (up from 718 / 49 at the start of the sprint); flake8 / isort / eslint clean.
> One pre-existing test (`test_fm_admin_can_list`) updated to account for the new
> platform-seeded `Site Composite` DeviceType.

---

### Sprint 28 — Interval Aggregation Engine + Data Quality Flags

**Goal:** Maintain rolling aggregates of stream readings at fixed periods (5 min / 30 min / 1 h / 1 d / 1 month) and tag every reading with a data-quality flag, so billing runs and dashboards can read aggregates instead of recomputing over raw, and invoices can identify intervals that weren't directly measured.

**Deliverables:**

_Interval aggregation (SPEC §3 Interval Aggregation Engine):_
- [x] Backend: `IntervalAggregate` model (stream, period, period_start, value, count, aggregation_kind, quality_breakdown JSONB) with `unique_together (stream, period, period_start, aggregation_kind)` and `(stream, -period_start)` index
- [x] Backend: Aggregation kinds — `sum`, `mean`, `min`, `max`, `last`; multi-kind supported via backfill `kinds` param
- [x] Backend: `Stream.aggregation_kind_default` field with `Stream.AggregationKind` enum
- [x] Backend: Period alignment helpers (`clock_align`, `period_end`, `previous_period_start`) — UTC-aligned 5min / 30min / 1h / 1d / 1mo
- [x] Backend: `compute_aggregate` aggregator core in `apps/readings/aggregates.py`; idempotent `update_or_create` on the unique key
- [x] Backend: `maintain_interval_aggregates` Celery beat task at 60s cadence — writes any newly-completed bucket for every active stream
- [x] Backend: `backfill_aggregates` Celery task + `POST /api/v1/streams/:id/aggregates/backfill/` (Tenant Admin) with optional `kinds` parameter
- [x] Backend: Read endpoint `GET /api/v1/streams/:id/aggregates/?period=&kind=&from=&to=&cursor=&limit=` with opaque base64 timestamp cursor pagination (max 1000/page)

_Data quality flags (SPEC §3 Data Quality Flags):_
- [x] Backend: `StreamReading.quality` enum (`measured` / `estimated` / `substituted` / `gap`), default `measured`
- [x] Backend: Derived streams (Sprint 27) now write inherited worst-input quality via `_upsert_output`
- [x] Backend: Aggregator marks periods with zero readings as `count=0, value=null, quality=gap`
- [x] Backend: `IntervalAggregate.quality_breakdown` JSONB — counts of source readings by quality; `IntervalAggregate.quality` is the worst-input roll-up
- [x] Backend: Reading endpoints include `quality` on every row; aggregate endpoints include `quality_breakdown` + the derived quality
- [x] Backend: 25 new tests in `apps/readings/tests/test_sprint28_aggregates.py` covering period alignment, per-kind correctness, idempotency, backfill (single + multi-kind), beat task, quality propagation through derived streams, LGC-style `quality=measured` filtering, pagination, cross-tenant 404, Tenant-Admin-only backfill
- [x] Frontend: `QualityBadge` component + 7 unit tests; rendered on the latest-value cell on the device Streams tab when quality != measured. Stream API responses now carry `latest_quality`.

**Definition of Done:**
- [x] A stream with one reading per period has 5-minute, 30-minute, hourly, daily, and monthly aggregates maintained automatically by the beat task
- [x] Backfill over a date range walks every bucket idempotently (`test_backfill_walks_all_buckets_in_range`, `test_backfill_multi_kind_in_one_pass`)
- [x] A period with no readings produces a `gap`-quality aggregate row (`test_zero_reading_period_produces_gap_aggregate`)
- [x] A derived stream computed from one `measured` and one `gap` input inherits `gap` quality (`test_derived_delta_inherits_gap_quality_from_source`)
- [x] Filtering by `quality=measured` excludes any aggregate that mixed in non-measured input (`test_lgc_filter_by_measured_only`)

> **Status (2026-05-28):** ✅ Complete. 798 backend tests + 62 frontend tests green
> (up from 773 / 55 at the start of the sprint); flake8 / isort / eslint clean.

---

### Sprint 29 — Meter Profiles & Billing Roles

**Goal:** Tag a Device as a billing meter with its metering attributes (NMI, role, phases, parent), tag Streams with their billing role, and prove the hierarchical-site write-time invariants — so Phase B2's billing engine knows which devices and streams carry billable energy.

**Deliverables:**
- [ ] Backend: `MeterProfile` one-to-one optional with `Device` — `nmi`, `meter_role`, `parent_meter_id`, `pattern_approval`, `phases`, `install_date`, `serial_number_secondary`
- [ ] Backend: `meter_role` enum — `gate`, `child`, `generation`, `storage`, `consumption`, `common_area`, `sub_check`
- [ ] Backend: `Stream.billing_role` (nullable enum) — `grid_import`, `grid_export`, `generation`, `bess_charge`, `bess_discharge`, `consumption`, `consumption_from_solar`, `net`
- [ ] Backend: `Site.is_hierarchical`, `Site.reconciliation_tolerance_percent`, `Site.common_area_apportionment_method`, `Site.embedded_network_exemption_id`
- [ ] Backend: Write-time enforcement — `gate` has no parent; `child` / `common_area` on a hierarchical site must point to a `gate` on the same site; at most one `gate` per site in v1; deactivating an active `gate` while children are active is blocked
- [ ] Backend: CRUD endpoints `/api/v1/devices/:id/meter-profile/` (Tenant Admin) and stream billing-role PATCH
- [ ] Backend: Bulk MeterProfile CSV import endpoint (Tenant Admin) — same pattern as reference-dataset CSV import; per-row errors returned
- [ ] Backend: Tests — invariant enforcement (every case), bulk import upsert + per-row errors, cross-tenant isolation, role permissions, deactivation guard
- [ ] Frontend: Meter Profile panel on device detail (Tenant Admin) — NMI, role, parent picker (scoped to gate meters on the same site), phases, install date
- [ ] Frontend: Stream billing-role inline editor on the device Streams tab
- [ ] Frontend: Bulk MeterProfile CSV upload UI (drag-and-drop, per-row error display)

**Definition of Done:**
- [ ] A device can be marked a meter with NMI + role; the meter shows on the device detail
- [ ] Marking a site as hierarchical and adding a `gate` meter unlocks the `child` / `common_area` workflow
- [ ] Adding a `child` meter without a parent on a hierarchical site is rejected with a clear error
- [ ] Bulk uploading 400 meter profiles via CSV completes in under 30 seconds with per-row validation errors
- [ ] Streams correctly carry their billing role and appear filtered in the billing-relevant stream picker

---

### Phase B1 Sign-Off Checklist
- [ ] All Sprint 0–29 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: configure a `delta` derived stream → publish raw readings → verify interval kWh stream values
- [ ] Manual smoke test: configure a cross-device `consumption_from_solar` → verify auto-created site composite Device
- [ ] Manual smoke test: 5-min / 30-min / 1-h / 1-d aggregates maintained automatically over a 24h window
- [ ] Manual smoke test: build a windowed-aggregate rule (avg > 30 over 15 min) and verify firing
- [ ] Hierarchical-site invariants verified manually (gate + 3 children + common area + reconciliation tolerance set)

---

### Sprint 29a — 3rd-Party API History / Backfill _(mini-sprint)_

**Goal:** Allow tenants to backfill historical interval data from a 3rd-party provider over a date range, on top of the existing live-poll path, without colliding with regular detail-endpoint polling.

**Context:** Some providers offer a date-range endpoint for historical data (e.g. `/history/?from=&to=`). Live polling (Sprint 10) handles the ongoing live feed but cannot cover the period before a tenant connects a data source. Slotted between B1 and B2 because the billing engine in B2 needs the option of operating against backfilled history. Folded in from SPEC §9 ⚑.

**Deliverables:**
- [x] Backend: `ThirdPartyAPIProvider.history_endpoint` config + `supports_history` flag + `history_chunk_days` (default 7); migration `0008_sprint29a_backfill`
- [x] Backend: `DataSourceBackfillJob` model — data_source, date_from, date_to, status (`queued` / `running` / `completed` / `failed`), rows_fetched + rows_stored progress counters, error_detail, started_at, finished_at, created_by
- [x] Backend: `integrations.run_backfill_job` Celery task — splits the window into `history_chunk_days` chunks, reuses the existing `{from_iso}/{to_iso}` interpolation against the history endpoint, iterates rows with provider-supplied timestamps, dedupes against existing `StreamReading` records on `(stream, timestamp)` before bulk_create
- [x] Backend: Dispatch + status endpoints `POST/GET /api/v1/data-sources/:id/backfill/`; provider must declare `supports_history`, range capped at 365 days, a single in-flight job per data source (409 on conflict)
- [x] Backend: Live-poll exclusion via `DataSourceDevice.is_backfilling` flag — beat task filters on `False`; backfill task sets/clears in `try`/`finally`; `integrations.reconcile_backfill_flags` Celery beat task (5-minute cadence) clears orphans against `DataSourceBackfillJob.status`
- [x] Backend: 22 tests in `apps/integrations/tests/test_sprint29a_backfill.py` — multi-chunk walk, idempotent dedup re-run, provider-supplied ISO + unix timestamps, is_backfilling lifecycle, HTTP failure path, live-poll exclusion, janitor reconciliation, all endpoint permission/validation cases
- [x] Frontend: `BackfillPanel` component on the DataSources page (visible only when `provider.supports_history`) — date range form, recent-jobs table, polls every 5s while any job is queued/running, surfaces error_detail under failed rows
- [x] Frontend: 5 tests in `components/BackfillPanel.test.jsx` covering empty state, submit, running-state disabling, failed-row error rendering, API error surfacing

**Definition of Done:**
- [x] Tenant Admin can request a backfill over a 90-day range for a connected data source that supports history
- [x] Backfill runs without duplicating readings already collected by live polling (`test_rerun_is_idempotent_no_duplicates`)
- [x] Backfill and live poll cannot run concurrently on the same `DataSourceDevice` (`test_backfilling_device_excluded_from_due_list`)
- [x] The Reporting CSV export for a backfilled stream over the historical window returns the backfilled rows (CSV export reads StreamReading directly; backfilled rows are stored with provider-supplied timestamps in the historical window)

> **Status (2026-06-01):** ✅ Complete. 883 backend tests + 67 frontend tests green
> (up from 798 / 62 at the start of the sprint); flake8 / isort / eslint clean.
> Lock mechanism: `is_backfilling` boolean on DataSourceDevice with janitor reconciliation
> (Redis SET NX deferred to the open SPEC §9 live-poll race condition fix). Pagination
> shape: day-window chunking with `history_chunk_days` per provider. No real provider
> seeded with `supports_history=True` — tests cover the surface against a mocked
> provider; the first real provider adds its own config in a follow-up.

---

### Phase B2 — Single-tier PPA Billing (Sprints 30–32)

> SPEC.md §3 (Billing Accounts & Tariffs, Billing Runs & Invoicing), §8 Phase 4c · B2.
> Builds on the `network-tariffs` dataset seeded in Sprint 15a; PPA retail-rate datasets to add.

---

### Sprint 30 — Billing Accounts, Tariffs & Bulk Import

**Goal:** Model the end customer (a `BillingAccount`) that the operator bills, link it to specific billed streams, and assign PPA tariff datasets — so Sprint 31's billing run has accounts, meters, and rates to compute against.

**Deliverables:**
- [ ] Backend: `BillingAccount` model — tenant FK, name, customer_reference, contact details, billing_address, abn, account_type (`ppa_host` / `en_tenant` / `internal`), optional parent_account_id, invoice_email_recipients, floor_area_sqm, activated_at, deactivated_at
- [ ] Backend: `BillingAccountMeter` model — billing_account FK, stream FK, effective_from, effective_to; stream-level linkage (one meter can carry several billing-role streams that bill to different accounts)
- [ ] Backend: `BillingAccountTariffAssignment` model — bridges a billing account to a `ReferenceDataset` (PPA tariff), optional stream scope, dimension_filter, version pin, effective_from / effective_to; reuses `TenantDatasetAssignment` row-resolution logic
- [ ] Backend: PPA tariff dataset schemas — generation, consumption-from-solar, feed-in — seeded via fixture (`backend/apps/feeds/fixtures/ppa_tariffs_template.json`); operators duplicate and customise
- [ ] Backend: CRUD endpoints — `/api/v1/billing-accounts/`, nested meter and tariff endpoints
- [ ] Backend: Bulk `BillingAccount` CSV import endpoint — column schema matches model fields; per-row errors returned
- [ ] Backend: `BillingAccountAuditLog` model + automatic write on every billing-account CRUD operation (who, when, before/after)
- [ ] Backend: `Tenant.gst_rate` (default 0.10), `Tenant.invoice_number_format`, `Tenant.invoice_pdf_template_id`, `Tenant.invoice_settlement_disclaimer` fields
- [ ] Backend: Tests — model invariants, CRUD permissions (Tenant Admin only), cross-tenant isolation, bulk import upsert + per-row errors, audit log immutability + automatic write
- [ ] Frontend: Billing Accounts nav item under a new "Billing" section
- [ ] Frontend: Billing Account list + create + detail page (lifecycle dates, meter assignments, tariff assignments, audit log tab)
- [ ] Frontend: Bulk CSV upload UI for billing accounts
- [ ] Frontend: "Tariffs" nav item — filtered view of `scope=tenant` Reference Datasets that are PPA tariffs

**Definition of Done:**
- [ ] A Tenant Admin can create a `ppa_host` billing account, link a `generation` stream to it, and assign a PPA generation tariff
- [ ] Bulk uploading 200 billing accounts via CSV completes with per-row validation errors
- [ ] Every billing-account CRUD operation writes an audit log entry with before/after diff
- [ ] `BillingAccountAuditLog` rows are immutable (no UPDATE / DELETE endpoints)
- [ ] Cross-tenant: Tenant B cannot read Tenant A's billing accounts on any endpoint

---

### Sprint 31 — Billing Run Engine

**Goal:** Run a billing period over an account set and produce reconciled, auditable per-customer line items. Snapshots the readings used so the run is reproducible. Non-hierarchical (PPA / single-tier) only — embedded-network logic lands in B3.

**Pre-sprint design decisions (locked 2026-05-29):**
- Aggregate period is run-level: `BillingRun.aggregate_period` ∈ {5min, 30min, 1h}, defaults to 30min.
- Run scope: `site_id` required in v1; `billing_account_ids` filters within the site (empty = all active). Lock key is `(site, period_start, period_end)`. Cross-site / portfolio runs deferred to v1.1.
- Mid-cycle pro-rata: engine clamps each account's billable window to `[activated_at, deactivated_at] ∩ run period`.
- Feed-in modeling: explicit `BillingAccountTariffAssignment` per account; engine emits `credit` line whenever the resolved tariff is on a `billing_role=grid_export` stream.
- GST: per-line `gst_cents = amount_cents × Tenant.gst_rate` (half-up rounding); summed to invoice totals (not a separate aggregate GST line).
- Retry checkpoints: 4 coarse named steps — `resolve_scope → snapshot → compute_line_items → mark_draft`. Each is one DB transaction. `failed_step` records which one threw; retry resumes from there; recompute (draft only) restarts from `resolve_scope`.
- Tariff precedence: stream-specific assignment beats catch-all (`stream=null`) for the same account + effective window.
- TOU handling: split intervals at peak/off-peak boundaries (line items aggregated per (account, stream, period_name) across the run).

**Scope note:** `finalize` and `void` endpoints land in Sprint 32 (coupled with invoice rendering). Sprint 31 takes runs as far as `draft`/`failed`; `retry` and `recompute` are wired. The `finalized` / `voided` status values are reserved in the enum but never set by Sprint 31 code.

**Deliverables:**

_Models + migration:_
- [x] `BillingRun` (tenant FK, site FK, billing_account_ids array, period_start/end, timezone_snapshot, aggregate_period enum, status enum, failed_step enum, failure_detail text, created_by, finalized_by, computed_at, finalized_at, voided_at)
- [x] `BillingRunSnapshot` (run FK, billing_account FK, stream FK, interval_aggregate_ids array, computed_kwh decimal, quality_summary JSONB) with unique `(run, account, stream)` constraint
- [x] `BillingLineItem` (run FK, billing_account FK, stream FK nullable, line_kind enum, period_name, kwh, rate_cents_per_kwh, amount_cents, gst_cents, quality_summary JSONB, source_account FK nullable)
- [x] `BillingSchedule` (tenant FK, name, site FK, billing_account_ids, aggregate_period, cadence enum, anchor_day, period_offset_days, custom_cron, auto_finalize, is_active, last_run_at, next_run_at)
- [x] Migration `0002_sprint31_runs`

_Engine (apps/billing/engine.py + tariff_resolver.py):_
- [x] `find_assignment(account, stream, on_date)` — stream-specific beats catch-all; raises on overlapping configurations
- [x] `split_interval(assignment, start_utc, end_utc, tenant_tz)` — minute-by-minute walk in tenant local time; yields `(row, fraction)` segments at TOU boundaries
- [x] Step 1 `resolve_scope`: validates site, finds active accounts, clamps each account's window
- [x] Step 2 `snapshot`: walks each account's billed streams, fetches `IntervalAggregate`s (`aggregation_kind=sum`) over the clamped window, writes `BillingRunSnapshot` rows; fails on streams linked to multiple accounts
- [x] Step 3 `compute_line_items`: per interval, resolves tariff + splits at TOU boundaries, accumulates per `(stream, period_name)`, writes one `BillingLineItem` per group; emits `credit` (sign-flipped) for `grid_export` streams; emits one `supply` line per account summed across billable days
- [x] Step 4 `mark_draft`: status=draft, computed_at=now
- [x] Per-line GST: `amount_cents × Tenant.gst_rate`, half-up rounding (Australian standard)
- [x] StepError surfaces failing step + message; engine writes status=failed, failed_step, failure_detail; recompute deletes prior snapshot/line items so re-runs are idempotent

_Celery tasks (apps/billing/tasks.py):_
- [x] `billing.run_billing_run` — Redis `SET NX` lock on `billing:run:lock:{site}:{period_start}:{period_end}` with 1h TTL; releases in `finally`; marks run failed on lock contention with a clear failure_detail
- [x] `billing.retry_billing_run` — refuses unless status=failed; resumes from `failed_step`
- [x] `billing.dispatch_billing_schedules` — beat task (60s cadence); creates + dispatches a `BillingRun` for the previous full cadence period in tenant tz; advances `next_run_at`
- [x] `_previous_period` + `_next_run_at` math for `monthly_calendar` / `monthly_anchor` / `quarterly` / `custom_cron` (custom_cron falls back to monthly_calendar in v1)

_API (apps/billing/views.py + serializers.py + urls.py):_
- [x] `BillingRunViewSet` with `list`, `retrieve`, `create` (Tenant Admin), `retry` (Tenant Admin, failed only), `recompute` (Tenant Admin, draft only), `line-items` (read), `snapshot` (read)
- [x] `BillingScheduleViewSet` with full CRUD (Tenant Admin); validates anchor_day required for `monthly_anchor`, custom_cron required for `custom_cron`
- [x] Cross-tenant access returns 404; ViewOnly can read, cannot write

_Beat config:_
- [x] `dispatch-billing-schedules` registered in `CELERY_BEAT_SCHEDULE` at 60s

_Tests (apps/billing/tests/test_sprint31_engine.py — 17 tests):_
- [x] Engine happy path: PPA flat tariff, 24h × 48 30-min intervals → energy + supply lines with correct GST
- [x] TOU split correctness across a 21:00 peak/off-peak boundary (1-hour interval splits 50/50)
- [x] Mid-cycle pro-rata: `deactivated_at` clamps the billable window
- [x] Stream-specific tariff beats catch-all on the same account
- [x] Same stream linked to two accounts → snapshot step raises with clear message
- [x] Feed-in `credit` line emitted (sign-negated) on `grid_export` stream
- [x] Per-line GST including negative GST on credit lines
- [x] API: admin creates run (202 + dispatch), operator blocked, cross-tenant 404, retry/recompute reject wrong-status, line-items list
- [x] Redis lock prevents concurrent runs on same (site, period) — second attempt marked failed
- [x] Retry resumes from `failed_step` (snapshot pre-populated, retry only re-runs compute_line_items)
- [x] BillingSchedule cadence math for `monthly_calendar`; `_next_run_at` advances; dispatcher creates a BillingRun on a past `next_run_at`

**Definition of Done:**
- [x] A PPA billing run over a 1-day period for one `ppa_host` account produces correct line items at the assigned generation tariff rate (24h, 48 × 30-min, 20 c/kWh → 960c energy + 200c supply + 10% GST per line)
- [x] A draft run can be recomputed; retry resumes from the failed step (`finalize` / `void` ship with Sprint 32)
- [x] Two concurrent run attempts on the same (site, period) — exactly one succeeds; the other is marked failed with a clear `failure_detail`
- [x] A failed engine step records `failed_step`; `retry` resumes from there without re-running prior steps
- [x] `BillingSchedule` dispatcher creates + dispatches a BillingRun when `next_run_at` has passed
- [x] Line items carry `quality_summary` rolled up from the source aggregates' `quality_breakdown`

> **Status (2026-06-02):** ✅ Complete. 900 backend tests passing under
> `pytest --cov=apps/` (the exact CI command); flake8 / isort clean over
> `apps/ config/`. Sprint 32 (Invoice Rendering, Delivery & Audit) introduces
> `finalize` / `void` and reuses the run's `BillingRunSnapshot` +
> `BillingLineItem`s unchanged.

---

### Sprint 32 — Invoice Rendering, Delivery & Audit

**Goal:** Render finalized billing runs as PDF invoices stored in object storage, deliver them by email, and lock everything immutable post-finalize. Closes Phase B2.

**Deliverables:**
- [ ] Backend: `BillingInvoice` model — billing_run FK, billing_account FK, invoice_number, subtotal, gst_amount, total_amount, pdf_storage_key, status (`draft` / `delivered` / `void`), created_at, delivered_at, voided_at
- [ ] Backend: Atomic per-tenant invoice-number sequence via `SELECT FOR UPDATE` on `Tenant.invoice_number_sequence`; format from `Tenant.invoice_number_format`
- [ ] Backend: WeasyPrint PDF rendering pipeline — per-tenant HTML/CSS template (FK on `Tenant.invoice_pdf_template_id`); stored in object storage at `invoices/{tenant_slug}/{YYYY}/{invoice_number}.pdf`
- [ ] Backend: Configurable settlement-grade disclaimer footer (`Tenant.invoice_settlement_disclaimer`) — rendered by default on `en_tenant` invoices, off for `ppa_host`
- [ ] Backend: In-app preview — signed short-lived URLs (15 min) via object storage; no public URLs
- [ ] Backend: Email delivery — one Celery task per invoice (so one bad address does not fail the run), 14-day signed URL in email, PDF attached
- [ ] Backend: Finalize endpoint `POST /api/v1/billing-runs/:id/finalize/` — locks the run, line items, invoices, and snapshot immutable; dispatches per-invoice email tasks
- [ ] Backend: Manual resend per invoice — `POST /api/v1/billing-invoices/:id/resend/`
- [ ] Backend: Void workflow — on `BillingRun.objects.void`, all invoices `delivered` get an auto void-notification email unless `silent_void=true`
- [ ] Backend: Line-item CSV export — `GET /api/v1/billing-runs/:id/line-items.csv` (streaming response, Admin only)
- [ ] Backend: Tests — per-tenant invoice-number atomicity, PDF generation, object-storage upload + signed URL, email delivery success + retry, finalize locks the run, void notification logic, immutability of finalized invoices, role permissions, cross-tenant isolation
- [ ] Frontend: Billing Run list + detail page (line items, invoices grid, status, retry / recompute / finalize / void controls per role)
- [ ] Frontend: Invoice detail with PDF preview iframe (signed URL); resend button; void status indicator
- [ ] Frontend: BillingSchedule management page (Tenant Admin) — cadence picker, period_offset, auto_finalize toggle

**Definition of Done:**
- [ ] A finalized PPA run delivers one PDF invoice per account to the recipient addresses with a 14-day signed download link
- [ ] Invoice numbers are sequential per tenant with no gaps and no duplicates under concurrent finalize
- [ ] Voiding a delivered finalized run sends one void-notification email per invoice unless `silent_void` is set
- [ ] Line items CSV export streams without timeouts on a 1000-row run
- [ ] PDF templates can be replaced per tenant without code changes

---

### Phase B2 Sign-Off Checklist
- [ ] All Sprint 0–32 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: end-to-end PPA — create billing account → assign generation tariff → run billing → finalize → confirm invoice delivered + accessible via signed URL
- [ ] Manual smoke test: void a finalized run and confirm void-notification emails sent
- [ ] BillingSchedule cron confirmed firing on the configured cadence
- [ ] Cross-tenant isolation confirmed across all billing endpoints

---

### Phase B3 — Embedded-Network Billing (Sprints 33–35)

> SPEC.md §3 (Embedded-Network Billing), §8 Phase 4c · B3.
> Hierarchical sites are gated by Sprint 29's `MeterProfile` invariants.

---

### Sprint 33 — Hierarchical Metering & Solar Allocation

**Goal:** Extend the billing run to hierarchical sites (gate + children + common area), computing per-interval solar allocation across child accounts pro-rata by `grid_import`. Produces split-rate tenant invoices (solar-allocated kWh + remaining-consumption kWh as two `energy` line items).

**Deliverables:**
- [ ] Backend: `BillingRun` algorithm extended to detect `Site.is_hierarchical` and switch to the hierarchical code path
- [ ] Backend: Per-interval solar pool computation — `pool = Σ generation − gate_export` (kWh that stayed inside the network), excluding `bess_discharge`
- [ ] Backend: Pro-rata allocation across active child accounts by `grid_import` interval value
- [ ] Backend: `SolarAllocationRecord` model — billing_run FK, interval timestamp, child_account FK, allocated_kwh, pool_kwh, child_grid_import_kwh; `unique_together (billing_run, interval, child_account)`
- [ ] Backend: Tenant invoice line items split into two `energy` lines per period — solar-allocated kWh at the solar (PPA) rate, remaining-consumption kWh at the grid (EN retail) rate
- [ ] Backend: BESS handling — `bess_discharge` does not count toward the solar pool; `bess_charge` reduces grid_import (per SPEC)
- [ ] Backend: Tests — single-gate single-child happy path, multi-child pro-rata correctness, BESS exclusion, an interval where solar = 0 produces no allocations, an interval where gate_export > generation (battery discharging out) caps the pool at 0, mid-cycle account onboarding pro-rates allocations correctly, idempotent on rerun, cross-tenant isolation

**Definition of Done:**
- [ ] A hierarchical site with 1 gate + 5 children + on-site solar produces 5 split-rate invoices with correct per-child solar shares
- [ ] Allocation totals across all children equal the solar pool exactly (no rounding leakage)
- [ ] Reproducible — re-running on the same period produces identical `SolarAllocationRecord`s
- [ ] PPA (non-hierarchical) runs are unaffected — Sprint 31 tests still pass

---

### Sprint 34 — Common-Area Apportionment & Reconciliation

**Goal:** Apportion common-area energy across tenant accounts using the per-site method, and reconcile the whole hierarchical run back to the gate meter — flagging variance beyond tolerance for operator review.

**Deliverables:**
- [ ] Backend: Common-area meter energy accumulates on an `internal` billing account (auto-created per common-area meter on first run); costed at the EN tariff
- [ ] Backend: Apportionment method per `Site.common_area_apportionment_method`:
  - [ ] `pro_rata_consumption` (default) — share by child grid_import for the period
  - [ ] `equal_share` — equal split across active child accounts
  - [ ] `by_floor_area` — share by `BillingAccount.floor_area_sqm`
- [ ] Backend: `common_area_share` line item on each child invoice — `source_account_id` links back to the internal account for audit
- [ ] Backend: `ReconciliationReport` model — billing_run FK, gate_import_kwh, generation_kwh, gate_export_kwh, child_grid_import_total_kwh, common_area_total_kwh, computed_losses_kwh, variance_percent, within_tolerance bool, created_at
- [ ] Backend: At run finalize, per period: `gate_import + Σ generation − gate_export` vs `Σ child_grid_import + common_area + losses`; variance beyond `Site.reconciliation_tolerance_percent` (default 1.5%) sets the run to `review` status — finalize blocked until operator confirms or recomputes
- [ ] Backend: Tests — apportionment correctness for each method, common-area auto-account creation, reconciliation within tolerance passes, variance over tolerance blocks finalize, idempotent on rerun, cross-tenant isolation
- [ ] Frontend: ReconciliationReport panel on the BillingRun detail (variance, within-tolerance badge, period-by-period breakdown)
- [ ] Frontend: Apportionment method picker on Site settings (Tenant Admin)

**Definition of Done:**
- [ ] A hierarchical site with a common-area meter produces a `common_area_share` line item on each child invoice using the configured method
- [ ] `by_floor_area` apportionment with one missing `floor_area_sqm` returns a clear validation error before the run starts
- [ ] A run with 5% variance is moved to `review`; the operator can investigate, recompute, or force-finalize with a note
- [ ] Reconciliation report shows the full math for every period — audit-quality

---

### Sprint 35 — EN Tariffs, Invoice Template, Compliance Export, Security Review

**Goal:** Ship the EN retail tariff dataset shape, the EN-specific invoice template, the per-site compliance data export operators need for AER reporting, and the B3-readiness security review — the gate before the first embedded network goes live. Closes Phase B3.

**Deliverables:**

_EN tariffs & invoice template:_
- [ ] Backend: EN retail tariff dataset schemas seeded via fixture — typical NMI-pattern × TOU shape, daily fixed supply charge, GST handling
- [ ] Backend: Invoice template registry — multiple `InvoicePDFTemplate` records per tenant; assignable on a per-account basis; EN-specific template included by default
- [ ] Backend: EN-specific template renders solar-allocation breakdown, common-area share, and the configurable settlement-grade disclaimer footer (`Tenant.invoice_settlement_disclaimer`)
- [ ] Backend: Tests — template selection per account type, EN solar / common-area breakdown rendering, disclaimer footer on/off, role permissions

_Compliance data export (SPEC §3 — not AER format templates):_
- [ ] Backend: `GET /api/v1/billing-runs/:id/compliance-export/` — per-period, per-site CSV / JSON covering per-account energy, solar-allocation totals, reconciliation status, comms-loss stats (gap/estimated counts), disconnections (deactivated accounts in period), billing disputes (operator-flagged)
- [ ] Backend: `BillingDispute` model — billing_invoice FK, raised_by, raised_at, status (`open` / `resolved`), notes; surfaced in compliance export
- [ ] Backend: Bulk billing-account CSV import already shipped in Sprint 30 — this sprint adds dispute import + tariff-assignment bulk operations
- [ ] Backend: Tests — compliance export shape, dispute lifecycle, cross-tenant isolation

_B3-readiness security review (gate):_
- [ ] At-rest encryption verification — Postgres + object storage (S3 / MinIO) encryption confirmed enabled in deployment guide
- [ ] NDB runbook drafted (Notifiable Data Breach response steps) — committed to `docs/security/ndb-runbook.md`
- [ ] APP 12 / APP 13 tooling scope — what export / correction tooling do we need before live operators ingest end-customer PII? Stub endpoints if required
- [ ] Privacy Impact Assessment — documented and signed off in `docs/security/pia-en-billing.md`
- [ ] Penetration test scope and timing decided (external test commissioned vs in-house)

**Definition of Done:**
- [ ] An embedded-network billing run produces invoices using the EN template with correct solar / common-area / disclaimer rendering
- [ ] Compliance export for a finalized run can be downloaded as CSV with all required columns
- [ ] NDB runbook, PIA, and APP 12/13 scope documents committed to the repo
- [ ] Security review formally signed off before any live tenant onboarding to an embedded network

---

### Phase B3 Sign-Off Checklist
- [ ] All Sprint 0–35 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: hierarchical site with 10+ children → run billing → invoices with solar + common-area split → reconciliation within tolerance
- [ ] Manual smoke test: force a reconciliation variance, confirm run blocked at `review` status
- [ ] Compliance export confirmed against a finalized run
- [ ] Security review documents committed and reviewed

---

### Phase B4 — Outbound Metering API (Sprints 36–37)

> SPEC.md §3 (Outbound Metering API), §8 Phase 4c · B4.

---

### Sprint 36 — Data Consumers & External API

**Goal:** Channel partners can call a normalised, scoped, read-only API for interval / daily / billing-run data. Authentication is separate from the tenant JWT so partner credentials cannot be confused with tenant logins.

**Deliverables:**
- [ ] Backend: `DataConsumer` model — tenant FK, name, api_key_hash (SHA-256), allowed_meter_ids JSONB, allowed_billing_account_ids JSONB, allowed_scopes JSONB (`intervals` / `daily` / `billing_runs` / `webhooks`), rate_limit_per_minute (default 60), created_at, last_used_at
- [ ] Backend: API key creation endpoint returns the raw key once on creation (one-time disclosure); subsequent reads expose only the hash + last_4
- [ ] Backend: API key rotation endpoint — issues new key, invalidates old
- [ ] Backend: `X-Consumer-Key` header auth middleware — distinct from `Authorization` JWT; explicit 401 if both headers are present (no confusion)
- [ ] Backend: `/api/v1/external/` URL namespace under its own router with its own permission classes
- [ ] Backend: Read-only endpoints (all scoped by consumer ACL):
  - [ ] `GET /api/v1/external/meters/` — meter list with NMI
  - [ ] `GET /api/v1/external/meters/:nmi/intervals/?from=&to=&period=` — interval kWh with `quality`
  - [ ] `GET /api/v1/external/meters/:nmi/daily/?from=&to=` — daily-close kWh with `quality`
  - [ ] `GET /api/v1/external/billing-runs/` — finalized billing runs list
  - [ ] `GET /api/v1/external/billing-runs/:id/` — run detail + snapshot
- [ ] Backend: Response normalisation — kWh units, UTC ISO 8601 timestamps, NMI on every row, `quality` on every interval; opaque base64 cursor pagination, max 1,000 rows per page
- [ ] Backend: Rate limiting per-consumer via Redis token bucket; 429 on overflow; per-consumer Prometheus metrics (`thatplace_external_request_count`, `thatplace_external_request_duration_seconds`, labels: consumer_id, endpoint, status)
- [ ] Backend: Tests — auth header confusion rejected, ACL enforcement (consumer cannot read meters/accounts not in allow-list), pagination cursor stability, rate limit enforcement, key rotation invalidates old key, cross-tenant isolation
- [ ] Frontend: Data Consumers management page (Tenant Admin) — create, view, rotate, revoke; one-time key display on creation; ACL editor

**Definition of Done:**
- [ ] A Tenant Admin can create a `DataConsumer`, see the raw API key exactly once, then never again
- [ ] A consumer with `allowed_meter_ids=[5]` cannot read meter 6 — 403 or filtered list (consistent across endpoints)
- [ ] Cursor pagination is stable across page boundaries even when rows are inserted concurrently
- [ ] A consumer exceeding `rate_limit_per_minute` gets 429 within one tick; Prometheus metric increments
- [ ] Tenant JWT cannot authenticate against `/api/v1/external/`; consumer key cannot authenticate against `/api/v1/`

---

### Sprint 37 — Webhooks (Consumer + Platform Notification) & Channel-Partner Docs

**Goal:** Channel partners receive HMAC-signed webhook events on key billing milestones, and the existing platform notification infrastructure gains outbound webhook delivery (Slack / PagerDuty / ops tooling) on top of in-app + email. Closes Phase B4 — and Phase B overall.

**Deliverables:**

_Consumer webhooks (SPEC §3 Outbound Metering API):_
- [ ] Backend: `DataConsumerWebhook` model — data_consumer FK, target_url, secret (32-byte random, shown once), event_types JSONB (`daily_close` / `billing_run_finalized` / `billing_run_voided` / `billing_account_lifecycle`), is_active, created_at
- [ ] Backend: Webhook dispatch — Celery task on the relevant event; POSTs to `target_url` with `X-That-Place-Signature: sha256=<hex>` header; payload signed with HMAC-SHA256 of the request body using the webhook secret
- [ ] Backend: At-least-once delivery — exponential-backoff retries at 1m, 5m, 30m, 4h, 24h; 2xx response = delivered, non-2xx = retry
- [ ] Backend: `WebhookDelivery` model — webhook FK, event_type, payload (JSONB), http_status, response_body_excerpt (first 500 chars), attempts, delivered_at (nullable), failed_permanently_at (nullable), last_attempt_at
- [ ] Backend: CRUD endpoints + delivery log endpoint `/api/v1/external-webhooks/:id/deliveries/`
- [ ] Backend: Manual retry endpoint for a specific delivery
- [ ] Backend: Tests — HMAC signature correctness, retry schedule (mocked clock), permanent failure after final retry, delivery log shape, signature secret rotation

_Platform notification webhook delivery (folded in from Backlog):_
- [ ] Backend: New `Notification.Channel.WEBHOOK` choice; reuses the consumer webhook delivery primitive (same HMAC + retry + log infrastructure)
- [ ] Backend: `NotificationEventType.default_channels` now accepts `webhook` alongside `in_app` / `email`
- [ ] Backend: `PlatformNotificationWebhook` model — global (not consumer-scoped), label (e.g. "Ops Slack"), target_url, secret, event_type_keys JSONB filter, is_active; That Place Admin only
- [ ] Backend: `emit_event` dispatch fan-out extended to write a webhook `Notification` row and queue dispatch when the target event type has webhook in its default_channels and at least one PlatformNotificationWebhook matches
- [ ] Backend: Tests — platform-notification webhook fires on `pending_device_approval`, `mqtt_broker_connectivity_failure`, signature correctness, retry path
- [ ] Frontend: That Place Admin — Platform Webhooks management page (list, create, edit, rotate secret, test-fire)

_Channel-partner documentation:_
- [ ] `docs/channel-partner-onboarding.md` — how to obtain a consumer key, ACL semantics, endpoint reference with examples, webhook signature verification code samples (Python, Node), retry semantics, rate limit policy
- [ ] OpenAPI / Swagger schema generated for the `/api/v1/external/` namespace

**Definition of Done:**
- [ ] A consumer webhook fires on `billing_run_finalized` with a valid HMAC signature within 30 seconds of finalize
- [ ] A webhook that returns 500 retries five times on the configured schedule then marks permanently failed
- [ ] A platform notification with the webhook channel delivers to a configured Slack ops endpoint
- [ ] Channel-partner docs are sufficient for a partner to integrate without internal handholding (verified by a dry-run integration)
- [ ] OpenAPI schema accurately describes every external endpoint

---

### Phase B4 Sign-Off Checklist
- [ ] All Sprint 0–37 tests passing (full cumulative suite — no failures, no skips)
- [ ] Manual smoke test: create DataConsumer → fetch intervals via API → finalize a billing run → confirm webhook delivered with valid signature
- [ ] Manual smoke test: a non-2xx webhook target retries and eventually permanently-fails
- [ ] Platform notification webhook confirmed delivering to an ops Slack endpoint
- [ ] OpenAPI schema published and channel-partner docs reviewed

---

**Phase B Final Sign-Off:**
- [ ] All Sprint 0–37 complete with passing tests (full cumulative suite)
- [ ] E2E sign-off journeys extended to cover at least one billing-run round trip
- [ ] No open P1 or P2 bugs across the billing engine
- [ ] SPEC.md, ERD.md, and `docs/channel-partner-onboarding.md` up to date
- [ ] Security review documents (NDB runbook, PIA, APP 12/13 scope) committed and reviewed
- [ ] Performance audit on a 1-tenant 100-account 1-month run completes inside the operator-acceptable cycle close window

---

## Phase 5c — Auth Core

### Sprint 38 — Multi-Tenant User Accounts

> **Pre-sprint design deep dive required before kickoff.** This sprint reverses
> the SPEC §4 "a user belongs to at most one tenant" rule — an auth-core change
> that touches the JWT, every permission class, the tenant-context middleware,
> and full cross-tenant isolation re-verification. Slotted after Phase B
> sign-off so the billing surface is stable before auth core changes.

**Goal:** Allow one email / login to belong to multiple tenants and switch between them via a personal settings page. Fully supersedes the Sprint 23b interim duplicate-email guard.

**Pre-sprint deep dive (must complete before deliverables start):**
- JWT shape — `active_tenant_id` claim, re-issuance flow on switch, refresh-token behaviour across switches
- Tenant context middleware — resolves *active* `TenantUser` from JWT claim instead of `User.tenantuser` OneToOne
- Permission class rework — every `IsTenantAdmin` / `IsOperator` / `IsViewOnly` resolves the active TenantUser
- UI surface — tenant switcher, "you are managing N tenants" UX, account-level vs tenant-scoped settings boundary
- Migration plan — how do existing single-tenant users move to the new shape without downtime? `TenantUser.user` `OneToOneField` → `ForeignKey` is straightforward; the JWT format change is the risk
- Cross-tenant isolation re-verification scope — every read endpoint must be exercised under "user is in tenants A and B; JWT says active=A; cannot see B data"

**Deliverables:**
- [ ] Backend: `TenantUser.user` `OneToOneField` → `ForeignKey`; migration preserves existing rows
- [ ] Backend: JWT customisation — `active_tenant_id` claim; tokens reissued on `POST /api/v1/auth/switch-tenant/`
- [ ] Backend: Tenant context middleware reworked to use the JWT claim; falls back to user's single TenantUser if exactly one
- [ ] Backend: Every permission class resolves the *active* TenantUser
- [ ] Backend: `GET /api/v1/auth/me/` returns `tenant_memberships` list + `active_tenant`
- [ ] Backend: Invite flow updated — inviting an email that already belongs to another tenant creates a second TenantUser (no error); duplicate-email guard from Sprint 23b removed
- [ ] Backend: Tests — full cross-tenant isolation re-verified (every read endpoint), tenant switch reissues JWT correctly, JWT with stale `active_tenant_id` (user removed from tenant) rejected, single-tenant users unaffected
- [ ] Frontend: Tenant switcher in the top nav when user has ≥ 2 tenants; switching calls `/auth/switch-tenant/` and replaces tokens
- [ ] Frontend: User profile page surfaces tenant memberships
- [ ] Frontend: Accept-invite flow updated to handle "already have an account" path — log in then accept (or merge if already logged in)
- [ ] Frontend: All tenant-scoped queries get a `queryClient.clear()` on tenant switch to prevent stale cache

**Definition of Done:**
- [ ] An email can hold an active TenantUser in two tenants simultaneously; the user can switch between them via the UI
- [ ] Cross-tenant isolation re-verified: with `active=A`, no API call returns Tenant B data
- [ ] A user with one tenant sees no UI change; the switcher is hidden
- [ ] Sprint 23b duplicate-email guard removed; the new path is what backstops the constraint
- [ ] SPEC.md §4 updated: a user can belong to multiple tenants (one active at a time per session)
- [ ] All existing cumulative tests still pass on the new auth core

---

## Backlog — Parked (hardware / external blockers)

> Remaining unscheduled items. The previous Backlog has been folded into Phase B
> and Sprint 38 per the 2026-05-28 planning round.

- **Legacy weatherstation / tbox / abb payload parsers** — SPEC §2 & §9 ⚑. Blocked on hardware-team payload-format input. Topic patterns are registered (Sprint 6); the parsers cannot be built until the formats are confirmed.
- **Legacy command format clarification** — SPEC §9 ⚑. Current command format sent to Scouts is inconsistent (strings, JSON, raw characters). Clarify with hardware team and define migration path before legacy command handling can be specced.

---

## Phase 6 — React Native Mobile App

> Plan this phase in detail when Phase B sign-off is complete.

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
