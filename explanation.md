# Sprint 25 — Integration Testing & Phase 1–5 Sign-Off

## Why this sprint existed

Sprints 0–24 built That Place feature by feature: auth, tenants, devices, ingestion,
dashboards, rules, alerts, notifications, commands, exports, push tokens. Each
sprint shipped with its own unit and integration tests, and every sprint enforced
"all cumulative tests must pass before the next sprint starts." That gave us strong
*per-feature* confidence.

What it did **not** give us is end-to-end confidence: that all those features still
work *together* through a real browser session, that the platform stays fast under
realistic load, and that cross-tenant isolation still holds across every endpoint
that's been added since Phase 1.

Sprint 25 is the cumulative sign-off for Phases 1–5 before the React Native mobile
phase begins. The goal: **prove the platform is ready for mobile work**, not just
that individual features pass their unit tests.

The three things this sprint had to deliver:

1. **End-to-end browser tests** covering the five user journeys named in ROADMAP.md
2. **Performance audit** against a realistic 100k-reading dataset — no endpoint
   over 500ms, no N+1 queries
3. **Security audit** — cross-tenant isolation, role matrix, auth bypass

All three landed with no findings except one real Sprint 21 bug that the E2E
suite surfaced (and that this sprint then fixed).

---

## The testing pyramid as of Sprint 25

That Place now has four independent test layers, each catching a different class
of problem:

| Layer | Tooling | Count | What it catches |
|---|---|---|---|
| Backend unit/integration | pytest + pytest-django | **703** | Serializer logic, model invariants, cross-tenant filters, permission classes, evaluators, route handlers, MQTT topic parsing, etc. |
| Frontend component | Jest + React Testing Library | **43** | Component rendering, state transitions, hook behaviour, form validation |
| End-to-end browser | Playwright (Chromium + Firefox) | **14** (7 specs × 2 browsers) | Vertical user journeys exercised through a real browser hitting a real backend, real MQTT broker, real Celery worker |
| Static checks | flake8, isort, eslint | n/a | Style, import order, dead code |

The backend pytest suite is the source of truth for correctness. The Playwright
suite is the source of truth for *integration* — proving the layers talk to each
other correctly under realistic conditions.

---

## What Sprint 25 actually added

### 1. The `/e2e/` Playwright suite

A brand-new top-level folder at the project root:

```
e2e/
  playwright.config.js     Chromium + Firefox, 1440×900 viewport, traces on failure
  global-setup.js          Logs in as both seeded users once; saves storage state
  fixtures/api.js          Thin DRF client + reseed helper used by every spec
  tests/
    smoke.spec.js          Sanity: storage state loads, both layouts render
    onboarding.spec.js     create tenant → invite → site → register device → approve
    ingestion.spec.js      MQTT publish → StreamReading stored → device detail shows it
    rules.spec.js          rule fires → alert created → acknowledge updates status
    commands.spec.js       send command → ack received → history reflects it
    export.spec.js         configure → download CSV → verify rows + header
  README.md                How to run the suite locally
  .gitignore               node_modules, test-results, storage, blob-report
```

#### How it works under the hood

Playwright drives a real Chromium and a real Firefox against the running Vite dev
server at `localhost:5173`, which talks to the running Django dev server at
`localhost:8000`, which talks to the real Mosquitto broker, real Celery worker,
real PostgreSQL — everything in the existing `docker-compose` stack. Nothing is
mocked. That's the point: the suite proves the whole pipeline works.

**Authentication:** Specs are slow to log in by hand for every test, so
`global-setup.js` runs once before the whole suite, logs in as both the seeded
That Place Admin and the seeded Tenant Admin, and saves their JWT-bearing
localStorage to `storage/tp-admin.json` and `storage/tenant-admin.json`. Specs
just open a browser context with that storage state and they're already logged in.

**Determinism:** Each spec calls `reseed()` in `beforeAll`, which executes the
`seed_e2e` Django management command inside the backend container. That wipes
volatile state (readings, alerts, commands, notifications) and any throwaway
tenants from previous spec runs, so every spec starts from a known world even
when chromium + firefox both run the same spec back to back.

**MQTT publishing from specs:** The five journeys that depend on telemetry
(ingestion, rules, commands, export) need to publish MQTT messages to the broker.
The seed command provisions a fixed-credential dynsec client called
`e2e-publisher` (password `e2e-publisher-password`) with broad publish ACLs on
`that-place/scout/#` and `fm/mm/#`. Each spec shells into the backend container
via `docker-compose exec -T backend python -` and pipes a short paho-mqtt script
that publishes the test payload. The Celery worker processes it like any other
real Scout message.

**Pragmatic vs. deep UI:** Per the steer at the start of the sprint, every spec
uses the UI for the *headline* journey but uses the API for setup that's already
well covered by unit tests. The rules spec is the clearest example: building a
rule through the multi-step rule builder is exhaustively covered by component
tests already, so the spec creates the rule via `POST /api/v1/rules/` and then
exercises the trigger → alert → acknowledge chain through the browser — which is
the part that has real integration risk.

#### What each E2E spec does

**onboarding.spec.js** — As That Place Admin: navigate to `/admin/tenants/new`,
fill the form, submit, verify the tenant detail page renders. On the same page,
fill the invite form, send it, confirm the success message. Switch to the seeded
Tenant Admin context, create a Site through the inline form, then register a
pending Device through the Devices page. Switch back to That Place Admin,
navigate to Pending Devices, approve. Final API check confirms the device's
status is `active`.

**ingestion.spec.js** — Look up the seeded `E2E-DEVICE-001` via the API. Publish
one `that-place/scout/E2E-DEVICE-001/telemetry` payload with `temperature`,
`Relay_1`, `_battery`, `_signal` fields. Poll the streams endpoint until the
stream auto-discovery creates a `temperature` Stream with a populated
`latest_value`. Navigate the browser to the device detail page, click the
Streams tab, assert the temperature row shows a number. Click the Health tab,
assert the device shows online, battery `88%`, signal `-62 dBm`.

**rules.spec.js** — Publish an initial low temperature reading to auto-discover
the stream. Create a rule via `POST /api/v1/rules/` with a single condition
`temperature > 50` and a notification action. Publish a high temperature reading.
Poll `/api/v1/alerts/?status=active` until the new alert appears. Navigate to
`/app/alerts`, confirm the alert is in the Active feed by rule name. Open the
alert detail, click Acknowledge, fill the optional note form, submit. Final API
check confirms `status=acknowledged` and `acknowledged_by_email` matches.

**commands.spec.js** — Navigate to the device detail, click the Commands tab,
click the `Set Relay` command button, click Send Command. Confirm the
"Command sent" toast. Confirm the history table shows a row with status `sent`.
Publish a cmd/ack MQTT message. Reload the page (React Query cache won't auto-
refetch in the test's lifetime), click Commands tab again, confirm the row now
shows `acknowledged`.

**export.spec.js** — Publish two temperature readings to seed the data. Navigate
to `/app/reporting`. Fill the From and To datetime-local inputs. Expand the
seeded device block, tick the temperature checkbox. Click Download CSV and
capture the download via `page.waitForEvent('download')`. Read the file off disk,
split into rows, assert the header has the expected columns
(timestamp, site_name, device_name, stream_label, value), and assert at least
two data rows are present and include the seeded device name.

---

### 2. Two new Django management commands

#### `seed_e2e` (apps/accounts/management/commands/seed_e2e.py)

Creates the deterministic E2E fixture. **Idempotent** — re-running clears
volatile state (StreamReadings, Streams, Alerts, CommandLogs, Notifications,
DeviceHealth, throwaway tenants from onboarding, residual devices and sites in
the canonical tenant) but preserves the canonical users and tenant so the
cached browser storage states from `global-setup.js` stay valid across runs.

Creates / refreshes:

- `e2e_tp_admin@test.thatplace.local` — That Place Admin (password `e2e-password`)
- `e2e_tenant_admin@test.thatplace.local` — Tenant Admin of `E2E Tenant`
- `E2E Tenant` with site `Default Site`
- `E2E Test Scout` device type — includes a `set_relay` command schema and
  `temperature` + `Relay_1` stream-type hints
- `E2E-DEVICE-001` — an approved Scout ready to ingest telemetry
- `e2e-publisher` dynsec client — fixed-credential MQTT publisher with broad
  publish ACLs on `that-place/scout/#` and `fm/mm/#`

#### `seed_perf_data` (apps/readings/management/commands/seed_perf_data.py)

Generates a realistic 100k-StreamReadings dataset distributed over the last 30
days for the perf audit. Idempotent — re-running tops up to the target count;
`--reset` deletes existing perf readings before regenerating. Configurable via
`--count` and `--days`. Uses `bulk_create` in 5k-row batches for speed.

The perf data lives under its own `Perf Audit Tenant` so it never collides with
the E2E fixture and can be reseeded or wiped independently.

---

### 3. One real bug found and fixed

The commands E2E spec surfaced a Sprint 21 follow-up: the `cmd/ack` MQTT topic
router only matched the **bridged** Scout form
(`that-place/scout/{scout}/{device}/cmd/ack`), not the **Scout-direct** form
(`that-place/scout/{scout}/cmd/ack`).

This was a real gap. Looking at the send-side code in
`apps/devices/tasks.py:send_device_command`, commands sent to a non-bridged
Scout publish to `that-place/scout/{serial}/cmd/{name}` — so the Scout's ack
naturally comes back on `that-place/scout/{serial}/cmd/ack`. That 3-segment
topic didn't match any registered pattern; the celery_worker logged
*"No pattern matched topic … — discarding"* and the CommandLog stayed at `sent`
until the 30-second timeout marked it `timed_out`.

Fix at `apps/ingestion/router.py:202` — added the
`that_place_v1_scout_cmd_ack` pattern with regex
`^that-place/scout/(?P<scout>[^/]+)/cmd/ack$`. The handler in
`apps/ingestion/tasks.py:_handle_command_ack` works unchanged because the parsed
device is resolved from `scout_serial`.

Regression coverage at `apps/ingestion/tests/test_router.py:179` — two new tests
in `TestThatPlaceV1CmdAck` covering both the bridged and Scout-direct forms.

This is exactly the kind of bug the cumulative sign-off is supposed to catch —
the unit tests for Sprint 21 passed because they only tested the bridged path;
the E2E spec exercised the Scout-direct path against a real seeded device and
the gap surfaced immediately.

---

### 4. Performance audit

The audit measured every hot endpoint against the 100k-reading dataset. Two
checks:

**Latency** (curl-timed wall clock, single request, warm process):

| Endpoint | Time |
|---|---:|
| `GET /api/v1/devices/` | 19 ms |
| `GET /api/v1/devices/:id/` | 18 ms |
| `GET /api/v1/devices/:id/streams/` | 21 ms |
| `GET /api/v1/streams/:id/readings/?limit=100` | 30 ms |
| `GET /api/v1/streams/:id/readings/?limit=1000` | 64 ms |
| `GET /api/v1/streams/:id/readings/?limit=10000` | 61 ms |
| `GET /api/v1/streams/:id/readings/?from=…&to=…&limit=50000` | 64 ms |
| `GET /api/v1/alerts/` | 22 ms |
| `GET /api/v1/rules/` | 19 ms |
| `GET /api/v1/sites/` | 16 ms |
| `GET /api/v1/users/` | 22 ms |
| `GET /api/v1/notifications/` | 17 ms |
| `GET /api/v1/notifications/unread-count/` | 16 ms |
| `GET /api/v1/exports/history/` | 48 ms |
| `GET /api/v1/dashboards/` | 18 ms |

Target was **<500 ms**. Worst measured was 64 ms — about an order of magnitude
under budget. The exports streaming response was deliberately not in this list
because it's a streaming download and wall-clock latency isn't the right metric.

**Query counts** (Django `connection.queries` against the same endpoints):

| Endpoint | Queries |
|---|---:|
| `/api/v1/devices/` | 5 |
| `/api/v1/devices/:id/streams/` | 5 |
| `/api/v1/streams/:id/readings/?limit=1000` | 5 |
| `/api/v1/alerts/` | 4 |
| `/api/v1/rules/` | 4 |

Single-digit query counts mean `select_related` and `prefetch_related` are
correctly applied across the serializers. No N+1 was found; no fixes were
needed.

---

### 5. Security audit

The audit ran a battery of probes against two real tenants:

- **Perf Audit Tenant** (admin: `perf@e2e.test`)
- **E2E Tenant** (admin: `e2e_tenant_admin@test.thatplace.local`)

Plus newly-created operator and viewer users in E2E Tenant for the role matrix.

| Probe | Expected | Actual |
|---|---|---|
| Tenant A reads Tenant B device by id | 404 | 404 |
| Tenant A reads Tenant B streams | 404 | 404 |
| Tenant A reads Tenant B stream readings | 404 | 404 |
| Tenant A sends command to Tenant B device | 404 | 404 |
| Tenant A `DELETE`s Tenant B device | 404 | 404 |
| Tenant A's device list does not contain Tenant B serials | clean | clean |
| Anonymous `GET /api/v1/devices/` | 401 | 401 |
| Anonymous `GET /api/v1/alerts/` | 401 | 401 |
| Anonymous `GET /api/v1/rules/` | 401 | 401 |
| Anonymous `GET /api/v1/notifications/` | 401 | 401 |
| `GET /api/v1/devices/` with malformed JWT | 401 | 401 |
| Operator `POST /api/v1/devices/` (admin-only) | 403 | 403 |
| Operator `POST /api/v1/rules/` (admin-only) | 403 | 403 |
| Operator `POST /api/v1/devices/:id/command/` (admin+operator) | 201 | 201 |
| Operator `GET /api/v1/alerts/` (all roles) | 200 | 200 |
| Viewer `POST /api/v1/devices/` | 403 | 403 |
| Viewer `POST /api/v1/rules/` | 403 | 403 |
| Viewer `POST /api/v1/devices/:id/command/` | 403 | 403 |
| Viewer `GET /api/v1/alerts/` | 200 | 200 |

Every probe matched expectations. Combined with the 703 existing pytest cases
(many of which are themselves cross-tenant or role-matrix tests), the platform's
permission and isolation surface is in good shape.

---

## Tests in detail — what the pytest suite actually covers

The 703 backend tests are organised by app and by sprint. The naming convention
makes it easy to see what's tested where. Here's the lay of the land as of
Sprint 25:

### apps/accounts (Sprints 1–4, 23b)
- `test_auth.py` — JWT login, refresh, logout blacklist, inactive user blocked,
  invalid credentials, expired token
- `test_users.py` — invite flow, invite-accept, role updates, removals,
  cross-tenant access denied, View-Only blocked from writes
- `test_tenants.py` — Tenant CRUD as That Place Admin, non-admin denied,
  duplicate slug rejected, deactivation blocks login
- `test_settings.py` — Tenant timezone update; persists on responses
- `test_groups.py` — NotificationGroup CRUD, system groups auto-maintained on
  role change
- `test_sprint23b.py` — Reference dataset delete guard (409 when in use), 
  tenant-users endpoint scoping, duplicate-email invite guard, accept-invite
  integrity backstop

### apps/devices (Sprints 5, 8, 13, 21)
- `test_devices.py` — DeviceType CRUD as That Place Admin, Device registration,
  approval flow, pending device cannot ingest, cross-tenant isolation
- `test_sites.py` — Site CRUD, tenant isolation
- `test_health.py` — DeviceHealth derivation, activity_level mapping, per-device
  threshold override, offline detection at threshold
- `test_sprint13.py` — Status indicator mappings, health/uptime widget data
- `test_commands.py` — Command validation against DeviceType, MQTT publish,
  ack handling, timeout detection, rule-triggered commands, role enforcement,
  cross-tenant command rejected
- `test_tasks.py` — Celery beat tasks (offline detection, command timeouts)

### apps/ingestion (Sprint 6, 7, 21)
- `test_router.py` — All registered topic patterns; v1 vs legacy parsing;
  unknown topics return None; **+2 new tests** added in Sprint 25 covering the
  Scout-direct cmd/ack pattern
- `test_mqtt_credentials.py` — Dynsec provisioning, scout ACL building,
  certificate vs password modes
- `test_pki.py` — Device certificate issuance, CA chain verification

### apps/readings (Sprint 7, 9, 22)
- `test_ingestion.py` — Telemetry parsing for v1 and legacy formats; stream
  auto-discovery; reserved health-key extraction; unapproved device rejected;
  topic_format auto-detection
- `test_streams.py` — Stream label/unit override; display_enabled toggle;
  preserves data when disabled
- `test_exports.py` — Streaming CSV format; multi-stream export; cross-tenant
  stream rejected; View-Only blocked; export history Admin-only

### apps/rules (Sprints 14, 16, 17)
- `test_sprint14.py` — Rule CRUD, RuleStreamIndex maintenance, audit log
  creation, cross-tenant isolation, role permissions
- `test_sprint16.py` — Rule evaluation: false→true fires, true→true suppressed,
  cooldown logic, schedule gate, AND/OR group combination, feed-channel and
  reference-value condition types, Redis atomic-flag concurrency safety
- `test_sprint17.py` — Staleness conditions: fires at threshold, clears on new
  reading, 2-minute minimum enforced, beat-task scheduling

### apps/alerts (Sprint 18)
- `test_sprint18.py` — Alert created on rule fire, duplicate prevention,
  acknowledge / resolve transitions, View-Only blocked from writes, status
  filtering

### apps/dashboards (Sprints 11–13, 19a)
- `test_dashboards.py` — Dashboard CRUD, widget CRUD, tenant isolation, edit
  flow, widget title validation

### apps/notifications (Sprints 19, 20, 23, 24)
- `test_sprint19.py` — In-app notification creation per targeted user, system
  events, unread count, mark-all-as-read
- `test_sprint20.py` — Email delivery, SMS opt-in enforcement, NotificationSnooze
  per (user, rule), snooze expiry
- `test_sprint23.py` — Notification event registry, central dispatch, retrofit
  of existing system events, all seven platform emitters
- `test_sprint24.py` — UserPushToken CRUD, cross-user scoping, Expo push fan-out,
  DeviceNotRegistered token cleanup

### apps/feeds (Sprint 15a, 23b)
- `test_sprint15a.py` — Feed provider polling, FeedReading idempotency,
  FeedChannelRuleIndex maintenance, reference dataset row resolution (flat,
  versioned, TOU), bulk CSV import upsert, cross-tenant assignment isolation
- `test_sprint23b.py` — Reference dataset delete guard
- `test_jsonpath_security.py` — JSONPath expressions sandboxed against
  injection
- `test_tasks.py` — Celery beat polling tasks

### apps/integrations (Sprint 10)
- `test_datasources.py` — DataSource + DataSourceDevice CRUD, device discovery
  via provider API
- `test_providers.py` — ThirdPartyAPIProvider CRUD, auth schema validation
- `test_polling.py` — Celery beat polling, OAuth2 password grant + refresh,
  retry with exponential backoff, health-warning on consecutive failures
- `test_auth_handlers.py` — Provider auth strategies
- `test_isolation.py` — Cross-tenant isolation on DataSource endpoints
- `test_rule_dispatch.py` — Rule dispatch on FeedReading creation

This is the deep correctness layer. Sprint 25 doesn't replace it — it
complements it with two new things: end-to-end browser coverage of the user
journeys, and a deliberate audit of what cumulative state has been built.

---

## How to actually run all of this

**Backend pytest** (full suite, ~10 min):

```
docker-compose exec backend pytest -q
```

**Frontend jest** (~5 sec):

```
cd frontend && npm test -- --watchAll=false
```

**Backend lint**:

```
docker-compose exec backend bash -lc "flake8 apps/ && isort --check-only apps/"
```

**Playwright E2E** (~2 min, both browsers):

```
cd e2e
npm install                # one-time
npm run install:browsers   # one-time
npm test
```

**Perf seed** (one-off, ~30 sec to generate 100k readings):

```
docker-compose exec backend python manage.py seed_perf_data
```

**E2E fixture seed** (idempotent, run before E2E or whenever you want a clean
fixture):

```
docker-compose exec backend python manage.py seed_e2e
```

---

## Final numbers

| Metric | Value |
|---|---:|
| Backend pytest | 703 / 703 |
| Frontend jest | 43 / 43 |
| Playwright E2E (Chromium + Firefox) | 14 / 14 |
| Backend lint (flake8, isort) | clean |
| Frontend lint (eslint) | clean |
| Hot endpoints under 500ms target | yes — all under 100ms |
| N+1 queries found | 0 |
| Cross-tenant leaks found | 0 |
| Real bugs surfaced + fixed | 1 (Sprint 21 cmd/ack router) |

Phases 1–5 are signed off. The platform is ready for Phase 6.
