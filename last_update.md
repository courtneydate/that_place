# LAST UPDATE — Project State Snapshot

> **Purpose:** Fast-start orientation for Claude Code. Read this first, then `SPEC.md` and
> `ROADMAP.md` only as needed. Captures where the project actually is vs. what the roadmap
> checkboxes claim.
>
> **Snapshot taken:** 2026-06-28
> **Branch:** `main` · **HEAD:** `9b65004 Sprint 32 updates`

---

## TL;DR — where we are

- **Code is complete and test-green through Sprint 32 (end of Phase B2 — Single-tier PPA Billing).**
- **The ROADMAP.md checkboxes are STALE.** Sprints 29, 30, and 32 are committed and passing but
  their boxes are unticked. Only Sprint 31's boxes got marked. Don't trust the checkboxes —
  trust git history + the code.
- **Next sprint = Sprint 33** (Phase B3 — Hierarchical Metering & Solar Allocation). Not started.

---

## Verified test status (full suites run 2026-06-27)

| Suite | Result |
|-------|--------|
| Backend `pytest --cov=apps/` | ✅ **933 passed**, 89% coverage, ~12m40s |
| Frontend `npm test` | ✅ **67 passed** (9 suites) |
| flake8 / isort / eslint | ✅ all clean |

All unchecked-but-committed sprint tests pass: Sprint 29 (`metering/tests/test_meter_profile.py`),
Sprint 30 (`billing/tests/test_billing_accounts.py`), Sprint 31 (`billing/tests/test_sprint31_engine.py`),
Sprint 32 (`billing/tests/test_sprint32_invoices.py`).

---

## What's built (by phase)

- **Phases 0–5 + 5b (Sprints 0–26):** complete — auth, tenants, users/roles, sites, notification
  groups, device types, registration/provisioning, MQTT ingestion (legacy + v2 routers), stream
  auto-discovery, device health, 3rd-party API integration, all 5 dashboard widgets, full rules
  engine (point-in-time / compound / windowed-aggregate / staleness / feed-channel / reference-value),
  alerts, in-app/email/SMS/push notifications, device commands, CSV export, platform-admin
  notification registry, per-rule opt-outs, Playwright E2E.
- **Phase B1 (Sprints 27–29a):** complete — derived/computed streams (`apps/readings/derived.py`),
  interval aggregation + data-quality flags, `MeterProfile` (`apps/metering/`), 3rd-party API
  history/backfill (`apps/integrations/`).
- **Phase B2 (Sprints 30–32):** **code-complete.** `apps/billing/` holds all 10 models:
  `BillingAccount`, `BillingAccountMeter`, `BillingAccountTariffAssignment`, `BillingAccountAuditLog`,
  `InvoicePDFTemplate`, `BillingRun`, `BillingRunSnapshot`, `BillingLineItem`, `BillingSchedule`,
  `BillingInvoice`. Engine, tariff resolver, invoice renderer (WeasyPrint + `templates/invoices/default.html`),
  Celery tasks, migrations `0001`→`0002_sprint31_runs`→`0003_sprint32_invoices`.

## What is NOT started

- **Phase B3 (Sprints 33–35)** — embedded-network billing. No `SolarAllocationRecord` /
  `ReconciliationReport` models exist yet. **This is the frontier.**
- **Phase B4 (Sprints 36–37)** — outbound metering API / data consumers / webhooks. No `DataConsumer`.
- **Sprint 21a** (3rd-party API provider commands) — deferred.
- **Sprint 38** (multi-tenant user accounts) — after Phase B.
- Legacy weatherstation/tbox/abb parsers + legacy command format — parked on hardware-team input.

---

## Known gaps (not surfaced by a test run)

- **No frontend tests exist for ANY billing UI.** The 67 green frontend tests do NOT cover
  `BillingAccounts`, `BillingAccountDetail`, `BillingRuns`, `BillingRunDetail`, `BillingSchedules`,
  `InvoiceDetail`, or `Tariffs`. Green frontend ≠ billing UI verified.
- New file `frontend/src/components/DimensionFilterInputs.jsx` and the `ProviderLibrary.jsx`
  additions have no tests.

---

## Uncommitted working-tree changes (as of snapshot)

Mixed polish/follow-up on top of the Sprint 32 commit — not a clean single sprint:
- New: `docs/derived_streams.md`, `frontend/src/components/DimensionFilterInputs.jsx`
- Modified frontend: `ProviderLibrary.jsx` (+~191, likely provider commands), `DeviceDetail.jsx` (+~165),
  `DerivedStreamBuilder.jsx`, `DatasetAssignments.jsx` (refactored to use `DimensionFilterInputs`),
  `LineChartWidget.jsx`, `TenantLayout.jsx`, plus the billing pages (BillingRunDetail/Runs/Schedules,
  InvoiceDetail, BillingAccountDetail), `Reporting.jsx`
- Modified backend: `readings/serializers.py`, `readings/views.py`, `readings/admin.py`, `feeds/views.py`
- **Fix applied 2026-06-27:** corrected a flake8 E231 (missing space after comma) in
  `apps/readings/admin.py:11` — part of this uncommitted set.

---

## Key commands & gotchas

```bash
# Bring the stack up (Docker Desktop must be running first)
docker compose up -d

# Full backend suite (the CI command) — takes ~12-13 min
docker compose exec -T backend pytest --cov=apps/ -q

# Frontend suite (run inside the frontend container)
docker compose exec -T frontend npm test -- --watchAll=false

# Lint gates (all part of definition-of-done)
docker compose exec -T backend flake8 apps/
docker compose exec -T backend isort --check-only apps/
docker compose exec -T frontend npx eslint src/
```

Gotchas:
- **Windows + Docker Desktop:** the engine pipe must be up first. If `docker compose` errors with
  `open //./pipe/dockerDesktopLinuxEngine`, start `"%ProgramFiles%\Docker\Docker\Docker Desktop.exe"`
  and wait ~10s for `docker info` to succeed.
- Use `docker compose exec -T` (no TTY) when driving from a non-interactive shell.
- **Never commit** — always leave committing to the user.
- Git line-ending warnings (LF→CRLF) on this repo are normal noise, not errors.

---

## Apps in the backend

`accounts · alerts · billing · dashboards · devices · feeds · ingestion · integrations ·
metering · notifications · readings · rules`
