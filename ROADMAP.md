# Fieldmouse — Development Roadmap

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
- [ ] Docker Compose stack: Django, PostgreSQL, Redis, Celery worker, Celery beat, Mosquitto (MQTT), MinIO (object storage), React dev server
- [ ] Django project structure: apps (`accounts`, `devices`, `ingestion`, `readings`, `rules`, `alerts`, `dashboards`, `notifications`), split settings (`base`, `dev`, `prod`, `test`)
- [ ] React (Vite) project structure: `pages/`, `components/`, `hooks/`, `services/`, `theme/`
- [ ] `.env.example` with all required variables documented
- [ ] GitHub Actions CI: lint (flake8, isort, eslint) + **full** test suite (pytest + jest, all apps, all sprints) on every PR — fails and blocks merge on any single test failure
- [ ] Base test configuration: pytest-django, factory-boy for fixtures, Jest + React Testing Library
- [ ] README.md with setup instructions

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
- [ ] Backend: `User` model, JWT login / token refresh / logout endpoints (SimpleJWT)
- [ ] Backend: Token blacklist on logout
- [ ] Backend: `IsAuthenticated` base permission class applied globally
- [ ] Backend: Tests — login happy path, invalid credentials, expired token, logout blacklists token
- [ ] Frontend: Login page (email + password form, validation, error states)
- [ ] Frontend: Auth context — stores tokens, auto-refreshes before expiry, clears on logout
- [ ] Frontend: Protected route wrapper — redirects unauthenticated users to login

**Definition of Done:**
- Can log in with valid credentials
- Invalid credentials show a clear error message
- Token refreshes silently in the background
- Logout clears session and redirects to login
- Accessing a protected route while unauthenticated redirects to login

---

### Sprint 2 — Tenant Management (Fieldmouse Admin)

**Goal:** Fieldmouse Admin can create tenants and send the first admin invite.

**Deliverables:**
- [ ] Backend: `Tenant` model (with timezone field), `TenantUser` model
- [ ] Backend: Fieldmouse Admin guard (`IsFieldmouseAdmin` permission class)
- [ ] Backend: Tenant CRUD endpoints (Fieldmouse Admin only)
- [ ] Backend: Invite endpoint — generates invite token, sends email via configured email backend
- [ ] Backend: Tests — CRUD happy path, non-admin access denied, invite sent, duplicate tenant slug rejected
- [ ] Frontend: Fieldmouse Admin layout (separate nav from tenant user layout)
- [ ] Frontend: Tenant list page, create tenant form, tenant detail / edit page
- [ ] Frontend: Send invite action on tenant detail

**Definition of Done:**
- Fieldmouse Admin can create, view, edit, and deactivate tenants
- Invite email is sent to the first Tenant Admin
- Non-Fieldmouse-Admin users cannot access tenant management endpoints (403 returned)
- Deactivated tenant users cannot log in

---

### Sprint 3 — Tenant User & Role Management

**Goal:** Tenant Admin can manage their organisation's users and roles.

**Deliverables:**
- [ ] Backend: Invite accept flow (set password from invite token)
- [ ] Backend: User list, role update, remove user endpoints — scoped to tenant
- [ ] Backend: `IsTenantAdmin`, `IsOperator`, `IsViewOnly` permission classes
- [ ] Backend: Tenant context middleware — resolves tenant from authenticated user
- [ ] Backend: Tests — invite flow, role change, removal, cross-tenant access denied, View-Only blocked from write endpoints
- [ ] Frontend: Accept invite page (set password)
- [ ] Frontend: User management page (list, invite, change role, remove)

**Definition of Done:**
- Invited user can accept invite and set their password
- Tenant Admin can invite, promote, demote, and remove users
- All role permission rules enforced on API (tested with cross-tenant and cross-role requests)
- Removed user immediately loses API access

---

### Sprint 4 — Tenant Settings, Sites & Notification Groups

**Goal:** Tenant Admin can configure their organisation's timezone, create sites, and manage notification groups.

**Deliverables:**
- [ ] Backend: Tenant settings endpoint (update timezone)
- [ ] Backend: Site CRUD endpoints (scoped to tenant)
- [ ] Backend: `NotificationGroup` + `NotificationGroupMember` models and endpoints
- [ ] Backend: Auto-maintained system groups (All Users, All Admins, All Operators) — derived from TenantUser roles
- [ ] Backend: Tests — site isolation, system group membership auto-updates on role change
- [ ] Frontend: Tenant settings page (timezone picker)
- [ ] Frontend: Site management page (list, create, edit, delete)
- [ ] Frontend: Notification groups page (list, create, manage members)

**Definition of Done:**
- Tenant Admin can set timezone — persists and is returned on API responses
- Sites are isolated per tenant — Tenant A cannot see Tenant B's sites
- System groups reflect current user roles automatically
- Custom groups can be created with arbitrary members

---

### Sprint 5 — Device Type Library & Device Registration

**Goal:** Fieldmouse Admin can define device types; Tenant Admin can register devices and go through the approval flow.

**Deliverables:**
- [ ] Backend: `DeviceType` model (with commands JSONB, stream type definitions, offline threshold, ack timeout)
- [ ] Backend: DeviceType CRUD (Fieldmouse Admin write, all authenticated read)
- [ ] Backend: `Device` model (with `topic_format`, `offline_threshold_override_minutes`, `gateway_device_id`)
- [ ] Backend: Device registration endpoint (creates device with status `pending`)
- [ ] Backend: Device approval endpoint (Fieldmouse Admin only)
- [ ] Backend: Tests — approval flow, pending device cannot ingest data, cross-tenant device isolation
- [ ] Frontend: Device type library page (Fieldmouse Admin — create/edit types, define commands and stream types)
- [ ] Frontend: Device registration form (Tenant Admin — name, serial, site, device type)
- [ ] Frontend: Pending device indicator + Fieldmouse Admin approval action
- [ ] Frontend: Device list page with status badges

**Definition of Done:**
- Fieldmouse Admin can create device types with stream type definitions and commands
- Tenant Admin can register a device — it appears as pending
- Fieldmouse Admin can approve or reject — approved devices become active
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
- [ ] Mosquitto broker running in Docker Compose with authentication
- [ ] Backend: Celery MQTT subscriber worker — subscribes to `fm/mm/+/#` and `fieldmouse/scout/+/#`
- [ ] Backend: Topic router — registered pattern matching, extracts (scout_serial, device_serial, message_type, stream_key) from any registered pattern
- [ ] Backend: Legacy v1 patterns registered (weatherstation, relays, tbox, admin)
- [ ] Backend: New v2 pattern registered
- [ ] Backend: Messages from unregistered/unapproved devices logged and discarded
- [ ] Backend: `topic_format` auto-detected and updated on Device record
- [ ] Backend: Tests — both topic formats parsed correctly, unknown device discarded, topic_format flips on format change

**Definition of Done:**
- MQTT worker starts with `docker-compose up` and connects to broker
- Test message on legacy topic format routed and parsed correctly
- Test message on new topic format routed and parsed correctly
- Message from unregistered serial number discarded and logged

---

### Sprint 7 — Stream Ingestion & Auto-Discovery

**Goal:** Incoming telemetry is stored as StreamReadings; new stream keys automatically create Stream records.

**Deliverables:**
- [ ] Backend: Telemetry message handler — creates `StreamReading` for known streams
- [ ] Backend: Stream auto-discovery — unknown stream key on approved device creates new `Stream` record with data_type defaulting to `numeric`
- [ ] Backend: `RuleStreamIndex` maintained on stream creation (no rules yet, but infrastructure ready)
- [ ] Backend: Ingestion pipeline performance test — target < 5s latency from receipt to stored reading
- [ ] Backend: Tests — happy path ingestion, stream auto-creation, duplicate reading handling, unapproved device rejected

**Definition of Done:**
- Sending a telemetry MQTT message results in a StreamReading in the database within 5 seconds
- A new stream key auto-creates a Stream record
- An unapproved device's messages are discarded with no data stored

---

### Sprint 8 — Device Health Monitoring

**Goal:** Device health is tracked in real time; offline detection runs automatically.

**Deliverables:**
- [ ] Backend: `DeviceHealth` record updated on every received message (last_seen_at, signal, battery, activity_level derived from thresholds)
- [ ] Backend: Health topic handler for Scout health messages
- [ ] Backend: Celery beat task — checks all active devices against their offline threshold, marks offline when exceeded
- [ ] Backend: Per-device threshold override respected
- [ ] Backend: Tests — activity_level derivation, offline detection at threshold, override respected
- [ ] Frontend: Device list — health status indicator (colour-coded: online/degraded/critical/offline)
- [ ] Frontend: Device detail — health tab (battery, signal, last seen, first active, activity level)

**Definition of Done:**
- Devices show correct health status on device list within 30 seconds of status change
- A device with no messages for longer than its threshold is marked offline
- Per-device threshold override overrides device type default

---

### Sprint 9 — Stream Configuration UI

**Goal:** Tenant Admin can configure how streams are labelled and which appear on dashboards.

**Deliverables:**
- [ ] Backend: Stream label, unit override PATCH endpoint
- [ ] Backend: Stream display enable/disable PATCH endpoint
- [ ] Backend: Tests — label/unit updates persist, display flag does not affect data storage
- [ ] Frontend: Streams tab on device detail — list all streams with current value, label/unit edit inline, display toggle

**Definition of Done:**
- Tenant Admin can rename streams and set units
- Toggling display off hides a stream from dashboard widgets but data continues to be stored
- Disabled streams still appear in the configuration list (just marked as disabled)

---

### Sprint 10 — 3rd Party API Integration

**Goal:** Fieldmouse Admin can add a provider; Tenant Admin can connect their account and have devices auto-discovered.

**Deliverables:**
- [x] Backend: `ThirdPartyAPIProvider` model + CRUD (Fieldmouse Admin)
- [x] Backend: `DataSource` + `DataSourceDevice` models
- [x] Backend: Device discovery endpoint — calls provider's discovery endpoint using tenant credentials, returns device list
- [x] Backend: DataSourceDevice connect endpoint — creates virtual Device records for selected devices
- [x] Backend: Celery beat poller — calls detail endpoint per active DataSourceDevice on provider's interval
- [x] Backend: OAuth2 password grant token handling + refresh
- [x] Backend: Poll failure logging, retry with exponential backoff, device health warning on consecutive failures
- [x] Backend: Tests — discovery flow, polling stores StreamReadings, auth failure handled, retry logic
- [x] Frontend: Fieldmouse Admin — provider library (create provider, define auth schema, discovery/detail endpoints, available streams)
- [x] Frontend: Tenant Admin — add data source (pick provider → enter credentials → discover devices → select devices → select streams)
- [x] Frontend: DataSource management page (list connected devices, add/remove devices)

**Definition of Done:**
- SoilScouts (or equivalent) provider can be configured by Fieldmouse Admin
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
- [ ] Backend: `Dashboard` + `DashboardWidget` CRUD endpoints
- [ ] Backend: Stream readings endpoint with `?from=&to=&limit=` filtering
- [ ] Backend: Tests — dashboard isolation per tenant, widget CRUD, time range filtering
- [ ] Frontend: Dashboard list page (create, delete, navigate between dashboards)
- [ ] Frontend: Dashboard canvas — fixed grid layout with column selector (1/2/3 cols)
- [ ] Frontend: Widget builder modal — stream picker (site → device → stream)
- [ ] Frontend: Value card widget — latest reading, trend indicator, time since last update
- [ ] Frontend: 30-second auto-refresh

**Definition of Done:**
- Can create a dashboard, set column count, add a value card widget bound to a stream
- Value card shows live data and updates every 30 seconds
- Dashboard is shared across all tenant users — all roles can see it

---

### Sprint 12 — Line Chart & Gauge Widgets

**Goal:** Tenant Admin can add line charts with multiple streams and dual Y-axes, and gauge widgets.

**Deliverables:**
- [ ] Frontend: Line chart widget — multiple streams per chart, dual Y-axis support, each stream as a separate line, configurable time range
- [ ] Frontend: Gauge widget — single stream, configurable min/max/threshold bands
- [ ] Frontend: Time range selector (last hour / 24h / 7d / 30d / custom)
- [ ] Frontend: Cross-device stream selection in widget builder

**Definition of Done:**
- Line chart renders multiple streams from different devices on the same chart
- Dual Y-axis works — left and right axis each have independently selected streams
- Gauge reflects current value with correct band colouring
- Time range change reloads chart data

---

### Sprint 13 — Status Indicator & Health/Uptime Chart Widgets

**Goal:** All 5 widget types are complete; dashboard layout is polished.

**Deliverables:**
- [ ] Frontend: Status indicator widget — colour/label driven by stream value mapped to device type's status indicator config
- [ ] Frontend: Health/uptime chart widget — online/offline history, battery and signal as line charts
- [ ] Frontend: Widget drag-to-reorder within grid
- [ ] Frontend: Responsive reflow — single column below 1024px
- [ ] Frontend: Edit widget — each widget has an edit action (e.g. gear/pencil icon) that re-opens the widget builder modal pre-populated with the widget's current config; saving calls the existing `PUT /api/v1/dashboards/:id/widgets/:widget_id/` endpoint and updates the widget in place without deleting and recreating it

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
- [ ] Backend: `Rule`, `RuleConditionGroup`, `RuleCondition`, `RuleAction`, `RuleStreamIndex`, `RuleAuditLog` models
- [ ] Backend: Rule CRUD endpoints (Tenant Admin only)
- [ ] Backend: `RuleStreamIndex` maintained automatically on rule create/edit/delete
- [ ] Backend: `RuleAuditLog` entry created on every rule save (before/after diff)
- [ ] Backend: Tests — cross-tenant isolation, Admin-only rule creation, RuleStreamIndex accuracy, audit log immutability

**Definition of Done:**
- Rules can be created with conditions and actions via API
- RuleStreamIndex correctly maps every referenced stream to the rule
- Every save creates an audit log entry with before/after field values
- Tenant B cannot read or modify Tenant A's rules

---

### Sprint 15 — Rule Builder Frontend

**Goal:** Tenant Admin can build a complete rule using the visual step-flow interface.

**Deliverables:**
- [ ] Frontend: Rule list page (list, enable/disable toggle, delete)
- [ ] Frontend: Rule builder — step flow (name/description → schedule gate → conditions → actions → review & save)
- [ ] Frontend: Schedule gate step — day multi-select (with Weekdays/Weekends/Every day shortcuts) + optional time window
- [ ] Frontend: Condition builder — add/remove groups, AND/OR per group, top-level AND/OR, stream picker (site → device → stream), operator dropdown filtered by stream data type, value input adapts to type (number/toggle/text)
- [ ] Frontend: Staleness condition option — select stream + enter threshold
- [ ] Frontend: Action builder — notification action (channels + groups/users + message template with variable hints), device command action (device + command picker, param form)
- [ ] Frontend: Review step — summary of all conditions and actions before saving
- [ ] Frontend: Rule detail page with audit trail tab

**Definition of Done:**
- Can build and save a complete rule with multiple condition groups and multiple actions
- Operator dropdown shows only valid operators for the selected stream's data type
- Schedule gate saves correctly and is reflected in review step
- Audit trail tab shows all historical changes with before/after values

---

### Sprint 16 — Rule Evaluation Engine

**Goal:** Rules evaluate automatically when qualifying readings arrive; firing is correct and race-condition safe.

**Deliverables:**
- [ ] Backend: Celery task dispatched on StreamReading save — looks up rules via `RuleStreamIndex`, evaluates each
- [ ] Backend: Schedule gate evaluation (day of week + time window in tenant timezone)
- [ ] Backend: Point-in-time condition evaluation (numeric/boolean/string operators)
- [ ] Backend: Compound condition group evaluation (AND/OR per group, top-level AND/OR)
- [ ] Backend: Re-triggering suppression — fire only on false→true transition
- [ ] Backend: Redis atomic flag (`SET rule:{id}:state NX`) for concurrency safety
- [ ] Backend: Cooldown logic — respect `cooldown_minutes` before re-firing after condition clears
- [ ] Backend: `Rule.current_state` and `last_fired_at` updated on every evaluation
- [ ] Backend: Tests — false→true fires, true→true suppressed, true→false clears state, cooldown respected, concurrent evaluation race condition test

**Definition of Done:**
- A rule with `temp > 30` fires exactly once when temperature crosses 30
- Stays suppressed while temperature remains above 30
- Fires again after temperature drops below 30 and rises above again
- Two simultaneous readings do not cause duplicate firing (Redis flag test)
- Schedule gate prevents firing outside the configured window

---

### Sprint 17 — Staleness Conditions & Rule Polish

**Goal:** Staleness conditions work; rule engine handles all edge cases.

**Deliverables:**
- [ ] Backend: Celery beat task (60s interval) — evaluates all active staleness conditions across all tenants
- [ ] Backend: Staleness condition fires when stream has not reported within `staleness_minutes`
- [ ] Backend: Staleness condition clears when stream reports again
- [ ] Backend: Minimum staleness threshold enforcement (2 minutes minimum)
- [ ] Backend: Tests — staleness fires after threshold, clears on new reading, 2min minimum enforced
- [ ] Frontend: Rule list page shows last fired time and current state badge
- [ ] Frontend: Rule detail shows current state, last fired, next earliest fire (if cooldown active)

**Definition of Done:**
- A staleness condition fires within 60 seconds of the threshold being exceeded
- Clears automatically when the stream reports again
- Configuring a threshold below 2 minutes returns a validation error

---

### Sprint 18 — Alerts

**Goal:** Rule firings create alerts; operators can manage alert status.

**Deliverables:**
- [ ] Backend: `Alert` record created atomically with rule firing (same Celery task as evaluation)
- [ ] Backend: Alert acknowledge endpoint (Admin + Operator) — accepts optional `acknowledged_note`
- [ ] Backend: Alert resolve endpoint (Admin + Operator)
- [ ] Backend: Alert list endpoint — active alerts and history, filterable by site/device/rule/status
- [ ] Backend: Tests — alert created on fire, duplicate alert prevention (one active per rule), acknowledge/resolve transitions, View-Only cannot acknowledge
- [ ] Frontend: Alert feed — active alert view (what is wrong right now)
- [ ] Frontend: Alert history tab — all past firings, filterable
- [ ] Frontend: Alert detail — rule name, triggered at, device/site, acknowledge action (single tap + optional note field), resolve action
- [ ] Frontend: Alert badge in navigation (count of active alerts)

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
- [ ] Backend: `Notification` model — supports both alert-triggered and system event types
- [ ] Backend: In-app notification creation on alert fire (per targeted user)
- [ ] Backend: System event notifications: device approved, device offline, device deleted, DataSource poll failure
- [ ] Backend: Unread count endpoint
- [ ] Backend: Mark as read endpoint
- [ ] Backend: Tests — notification created per targeted user, system events generate notifications, unread count accurate
- [ ] Frontend: Notification bell in nav with unread badge
- [ ] Frontend: Notification dropdown/panel — list with unread indicators, tap to navigate to related alert
- [ ] Frontend: Mark as read on open

**Definition of Done:**
- Alert fire generates in-app notifications for all targeted users
- Device going offline generates a system notification
- Unread badge count is accurate
- Tapping a notification navigates to the relevant alert

---

### Sprint 20 — Email & SMS Notifications

**Goal:** Users receive email and SMS notifications on alert fire; opt-out is respected.

**Deliverables:**
- [ ] Backend: Email delivery via configured SMTP backend (AWS SES or any SMTP provider — set via `EMAIL_*` env vars)
- [ ] Backend: SMS delivery via chosen provider
- [ ] Backend: Per-channel user preferences — in-app and email on by default, SMS off by default (opt-in)
- [ ] Backend: SMS blocked at delivery if user has not opted in, regardless of rule action channels
- [ ] Backend: Delivery failure logging and single retry
- [ ] Backend: User notification preferences endpoint
- [ ] Backend: Tests — email sent to targeted users, SMS not sent to non-opted-in user, opted-out user not emailed, failure logged, retry attempted
- [ ] Frontend: User profile / notification preferences page — email/in-app toggles (default on), SMS toggle (default off, with explanation that SMS must be explicitly enabled)

**Definition of Done:**
- Alert fires trigger in-app and email to targeted users by default
- SMS only sent to users who have explicitly opted in
- A user who has opted out of email does not receive email notifications
- Failed deliveries are logged with error detail and retried once

---

### Sprint 21 — Device Commands

**Goal:** Admin and Operator can send commands to devices; commands are logged and ack tracked.

**Deliverables:**
- [ ] Backend: Command send endpoint — validates command and params against device type definition, publishes to MQTT
- [ ] Backend: MQTT ack listener — receives ack, updates CommandLog
- [ ] Backend: Timeout detection Celery task — marks CommandLog as `timed_out` after device type timeout period
- [ ] Backend: CommandLog CRUD (history endpoint)
- [ ] Backend: Tests — command validated against device type, ack received updates log, timeout fires correctly, View-Only blocked
- [ ] Frontend: Send command button on device detail (Admin + Operator only)
- [ ] Frontend: Command picker — shows commands registered for this device type
- [ ] Frontend: Command param form — auto-generated from param schema (number input, toggle, text field per param type)
- [ ] Frontend: Command history tab on device detail

**Definition of Done:**
- Can send a command from the UI — appears in command history with status `sent`
- Mock ack received — status updates to `acknowledged`
- No ack within timeout period — status updates to `timed_out`
- View-Only user cannot see the send command button

---

### Sprint 22 — CSV Data Export

**Goal:** Admin and Operator can export stream data as a streaming CSV download.

**Deliverables:**
- [ ] Backend: `StreamingHttpResponse` CSV export endpoint — queries readings in batches, streams rows to client
- [ ] Backend: CSV format: one row per timestamp, wide format with value+unit column pairs per stream
- [ ] Backend: `DataExport` log entry created on each export
- [ ] Backend: Export history endpoint (Admin only)
- [ ] Backend: Tests — CSV format correct, multi-stream export correct, large dataset does not timeout, non-Admin cannot view history
- [ ] Frontend: Data export page — date range picker + multi-stream selector
- [ ] Frontend: Download CSV button — triggers streaming download
- [ ] Frontend: Export history table (Admin only)

**Definition of Done:**
- Export with 3 streams over 30 days downloads as a single correctly formatted CSV
- Large exports do not timeout (streaming confirmed)
- Export history shows correct metadata
- Operator can export but cannot see history

---

### Sprint 23 — Fieldmouse Admin Notifications & Platform Events

**Goal:** Fieldmouse Admins receive notifications for platform-level events.

**Deliverables:**
- [ ] Backend: Fieldmouse Admin notification generation for: pending device approvals, MQTT broker connectivity failures, 3rd party API provider failures affecting multiple tenants
- [ ] Backend: Notification event registry — centralised registration of event types (not hardcoded)
- [ ] Backend: Tests — each platform event generates correct notifications, only Fieldmouse Admins receive them
- [ ] Frontend: Fieldmouse Admin notification panel (separate from tenant user notifications)

**Definition of Done:**
- Pending device creates a notification for all Fieldmouse Admins
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
