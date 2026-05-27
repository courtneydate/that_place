# That Place — Playwright E2E Tests

End-to-end tests for the five sign-off journeys defined in Sprint 25 of the roadmap:

1. **Onboarding** — create tenant -> invite admin -> set up site -> register device -> approve device
2. **Ingestion** — send MQTT reading -> verify StreamReading -> verify health update
3. **Rules** — build rule -> trigger condition -> alert fires -> notification received -> acknowledge
4. **Commands** — send command -> ack received -> history logged
5. **Export** — configure export -> download CSV -> verify format

Tests run against the full local Docker Compose stack. They are NOT a substitute for
the backend pytest suite or the frontend jest suite, which remain the source of truth
for unit / integration coverage.

## Prerequisites

- `docker-compose up -d` (backend on `:8000`, frontend on `:5173`, MQTT broker on `:1883`)
- Node 20+
- Browsers installed: `npm run install:browsers`

## Setup

```
cd e2e
npm install
npm run install:browsers
```

## Run the suite

One command — checks the stack is up, reseeds the fixture, runs Playwright:

```
npm run e2e                              # both browsers, headless
npm run e2e -- --project=chromium        # chromium only
npm run e2e -- -g "rule fires"           # single test by name
npm run e2e -- --headed                  # watch it click through
```

Anything after `--` is forwarded to `playwright test`.

### Direct Playwright (skips the preflight + reseed)

Useful when iterating on a single spec and you know the fixture is fresh:

```
npm test                  # both browsers, headless
npm run test:chromium     # Chromium only
npm run test:headed       # Watch it work
npm run test:ui           # Playwright UI mode
npm run report            # Open the last HTML report
```

### What the fixture looks like

`npm run e2e` seeds (idempotently) before each run:

- `e2e_tp_admin@test.thatplace.local` (That Place Admin, password `e2e-password`)
- `e2e_tenant_admin@test.thatplace.local` (Tenant Admin of `E2E Tenant`, password `e2e-password`)
- `E2E Tenant` with one `Default Site`
- `E2E Test Scout` device type with one approved device (`E2E-DEVICE-001`)
- `e2e-publisher` MQTT dynsec client (password `e2e-publisher-password`)

Reseeding clears volatile state (readings, alerts, commands, notifications) but
preserves the canonical tenant + users so cached browser storage states stay valid.

## Configuration

Environment variables (defaults shown):

| Variable           | Default                  | Purpose                                |
| ------------------ | ------------------------ | -------------------------------------- |
| `E2E_FRONTEND_URL` | `http://localhost:5173`  | Vite dev server URL                    |
| `E2E_BACKEND_URL`  | `http://localhost:8000`  | Django dev server URL                  |
| `E2E_MQTT_HOST`    | `localhost`              | Mosquitto host (port 1883)             |
| `E2E_PASSWORD`     | `e2e-password`           | Password for both seeded users         |

## Folder layout

```
e2e/
  playwright.config.js     Test runner config (Chromium + Firefox)
  global-setup.js          Logs in as both users once; caches storage state
  scripts/run-e2e.js       Preflight + reseed + run wrapper used by 'npm run e2e'
  fixtures/                Reusable helpers (api client, reseed)
  tests/
    smoke.spec.js
    onboarding.spec.js
    ingestion.spec.js
    rules.spec.js
    commands.spec.js
    export.spec.js
  storage/                 Generated storage states (gitignored)
```
