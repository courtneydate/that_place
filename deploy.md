# Deployment Guide — That Place

> **Purpose:** the single source of truth for standing up That Place in each
> environment, from a laptop to production. It is a **living document** — it
> grows one stage at a time as we promote the platform up the pipeline.
>
> **Current state (2026-07-07):** Stage 1 (Local Development) is complete and
> in daily use. Stages 2–3 (Staging / Production) document the *target*
> architecture and the concrete work still outstanding — **no production
> environment has been stood up yet.** See [Production readiness — open
> items](#production-readiness--open-items) for the gap list, and the note at
> the end about scheduling a production sprint.

---

## Deployment stages

| Stage | Status | Purpose |
|-------|--------|---------|
| 1. Local development | ✅ Working | Full stack on one machine via Docker Compose. Every contributor runs this. |
| 2. Staging | ⛔ Not built | A production-shaped environment for shaking out real-world/production-only bugs early. |
| 3. Production | ⛔ Not built | Customer-facing environment. AWS (preferred) or self-hosted Linux. |

Staging and production share the **same images and settings module**
(`config.settings.prod`); only env vars, secrets, and scale differ. The design
rule (SPEC §7): all external services are configured via environment variables —
no AWS SDK calls are hardcoded, so the same code path serves AWS and self-hosted.

---

## Stage 1 — Local development environment

### 1.1 Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Node.js 20+](https://nodejs.org/) — for the frontend dev server
- [Python 3.12+](https://www.python.org/) — only needed for running tooling outside Docker
- [Git](https://git-scm.com/)

### 1.2 Clone and configure

```bash
git clone <repo-url>
cd that_place
cp .env.example .env
```

The defaults in `.env.example` are wired for local Docker networking
(`postgres`, `redis`, `mosquitto`, `minio` hostnames) and work out of the box.
The `change-me` / `your-...-here` placeholder secrets are fine for local dev but
**must** be replaced before any shared environment — see
[2.3 Required production env vars](#23-required-production-secrets--env-vars).

### 1.3 The stack

`docker-compose up -d` starts nine services:

| Service | Container | URL / port | Notes |
|---------|-----------|-----------|-------|
| Django API | `backend` | http://localhost:8000 | `manage.py runserver` (dev only) |
| React web app | `frontend` | http://localhost:5173 | Vite dev server |
| PostgreSQL | `postgres` | localhost:5432 | DB/user/pass `that_place` |
| Redis | `redis` | localhost:6379 | Celery broker + result backend |
| Celery worker | `celery_worker` | — | `celery -A config.celery worker` |
| Celery beat | `celery_beat` | — | DatabaseScheduler (django_celery_beat) |
| MQTT subscriber | `mqtt_subscriber` | — | `manage.py start_mqtt` — ingestion listener |
| Mosquitto broker | `mosquitto` | localhost:1883 (plain), 8883 (mTLS) | Dynamic Security plugin |
| MinIO | `minio` | http://localhost:9000 (API), :9001 (console) | S3-compatible object storage |

### 1.4 First-run bootstrap

```bash
docker-compose up -d
```

On first start the stack self-bootstraps:

- **MQTT PKI + Dynamic Security** — the `mosquitto` container's
  `docker/mosquitto/entrypoint.sh` auto-generates a self-signed CA, broker cert,
  and the `that-place-backend` client cert, and initialises
  `dynamic-security.json` from `MQTT_ADMIN_USERNAME` / `MQTT_ADMIN_PASSWORD`.
  The generated base64 cert values are printed to the container log for copying
  into `.env` if you want the backend to use mTLS locally.
  > `docker/mosquitto/dynamic-security.json` is **runtime state** (holds per-device
  > credential hashes) and is git-ignored — never commit it.
- **MinIO bucket** — create the `that-place` bucket once, via the console at
  http://localhost:9001 (login with `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
  from `.env`) or the CLI. The app does not auto-create it.

Then run migrations and create an admin user:

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py createsuperuser
```

### 1.5 Seed data (optional)

```bash
# Reference datasets (network tariffs, CO2 factors) + AEMO NEM feed provider
docker-compose exec backend python manage.py load_reference_data

# A complete demo tenant for the E2E journeys
docker-compose exec backend python manage.py seed_e2e

# Bulk StreamReadings for performance testing
docker-compose exec backend python manage.py seed_perf_data
```

### 1.6 Frontend dev server

The `frontend` container runs Vite, but for hot-reload development you can also
run it on the host:

```bash
cd frontend && npm install && npm run dev
```

### 1.7 Verify it's up

- API: http://localhost:8000/api/v1/ (should require auth)
- Web app: http://localhost:5173
- `docker-compose ps` — all services `Up`; `postgres` shows `(healthy)`

### 1.8 Tests, lint, and phase sign-off checks

```bash
# Backend test suite (the CI command)
docker-compose exec backend pytest --cov=apps/ -q

# Backend lint (run before every hand-off)
docker-compose exec backend flake8 apps/
docker-compose exec backend isort --check-only apps/

# Frontend
cd frontend && npm test -- --watchAll=false
cd frontend && npx eslint src/

# Repeatable, non-destructive phase sign-off smoke checks (drive the live stack)
docker-compose exec backend python manage.py smoke_b1   # Phase B1
docker-compose exec backend python manage.py smoke_b2   # Phase B2
```

### 1.9 Using the app — a first walkthrough

Two ways to get a login you can use immediately:

**Option A — seed the demo fixture (fastest):**

```bash
docker-compose exec backend python manage.py seed_e2e
```

Creates ready-to-use accounts (both share password `e2e-password`):

| Role | Email | What they see |
|------|-------|---------------|
| That Place Admin (platform) | `e2e_tp_admin@test.thatplace.local` | Device Type library, tenant management, device approvals, all tenants |
| Tenant Admin | `e2e_tenant_admin@test.thatplace.local` | The `E2E Tenant` org — sites, devices, dashboards, rules, users |

Plus tenant `E2E Tenant`, site `Default Site`, device type `E2E Test Scout`, and
an approved device `E2E-DEVICE-001` ready to ingest telemetry.

**Option B — create your own platform admin:**

```bash
docker-compose exec backend python manage.py createsuperuser
```

A superuser is automatically a **That Place Admin** (`is_that_place_admin=True`),
so you can then walk the full onboarding flow yourself.

**Log in:** open the web app at http://localhost:5173 and sign in. The UI adapts
to the role — That Place Admins get the platform console (device types, tenants,
approvals); tenant users get their organisation's console.

**The two-tier model:**

- **That Place Admin** (platform staff) — device type library, approve device
  provisioning, 3rd-party provider library, access across all tenants.
- **Tenant roles** — Admin (full org control), Operator (dashboards, commands,
  acknowledge alerts, export), View-Only (read).

**Full onboarding flow (SPEC §3):**

1. As **That Place Admin**: create a Tenant, then send the first Tenant Admin an invite.
2. Dev sends email via the **console backend**, so the invite link appears in the
   backend logs rather than a real inbox:
   ```bash
   docker-compose logs -f backend
   ```
   Copy the link (built from `FRONTEND_URL`) to accept the invite and set a password.
3. As **Tenant Admin**: create Sites, then register Devices — they start **pending**.
4. As **That Place Admin**: approve the pending device → it becomes **active** and
   MQTT credentials are provisioned automatically.
5. Send telemetry (below) → streams auto-discover → configure streams, build
   dashboards, write rules, and wire alerts.

**Send test telemetry (exercise ingestion + health):**

```bash
docker-compose exec backend python manage.py send_test_telemetry --duration 60 --interval 5
```

Publishes both legacy-v1 and v2 telemetry to Mosquitto, auto-creating test
devices, storing `StreamReading`s, and updating `DeviceHealth`. Useful flags:
`--v2-serial`, `--interval`, `--duration`, `--broker-host` / `--broker-port`
(defaults to the plain 1883 listener), and `--cleanup` to delete the test data
afterward. Watch it flow through:

```bash
docker-compose logs -f mqtt_subscriber celery_worker
```

**Then try the rest of the platform:**

- **Dashboards** — add value-card / line-chart / gauge / status / health widgets bound to a stream.
- **Rules & alerts** — build a threshold rule, publish telemetry that crosses it, watch an Alert fire and a notification appear, then acknowledge / resolve it.
- **Commands** — send a device command (Admin / Operator) and see it in command history.
- **Reporting** — export stream data as CSV.
- **Billing (Phase B)** — billing accounts, tariffs, runs, invoices; the `smoke_b1` / `smoke_b2` commands (§1.8) drive this surface end-to-end.

### 1.10 Common issues

- **Port already in use (5432 / 8000 / 9000 / …)** — another project (or a prior
  stack) holds the host port. Stop the offending container
  (`docker ps` → `docker stop <name>`) or remap the port. Internal
  container-to-container traffic uses service hostnames and is unaffected by
  host-port conflicts.
- **`dynamic-security.json` shows as modified in git** — it is runtime state and
  git-ignored; if it is still tracked from an old commit, `git rm --cached
  docker/mosquitto/dynamic-security.json`.
- **MinIO uploads fail** — the `that-place` bucket hasn't been created (see 1.4).

---

## Stage 2 — Staging  ·  Stage 3 — Production  *(target — not yet implemented)*

Staging and production are the same build with production settings; staging is
simply a smaller, non-customer instance used to catch production-only bugs
early. **Everything below is the intended target — the artifacts marked ⛔ do
not exist in the repo yet.**

### 2.1 Architecture (SPEC §7 — Deployment Options)

| Component | AWS deployment (preferred) | Self-hosted deployment |
|-----------|---------------------------|------------------------|
| Compute | EC2 (ap-southeast-2) | Any Linux VPS / dedicated server |
| Database | RDS PostgreSQL | PostgreSQL (Docker or system service) |
| Cache / broker | ElastiCache Redis | Redis (Docker or system service) |
| Object storage | AWS S3 | MinIO (S3-compatible) |
| MQTT broker | AWS IoT Core or Mosquitto | Mosquitto (mTLS, port 8883) |
| Email | AWS SES | Any SMTP (Mailgun, Postmark, …) |
| TLS | ACM | Let's Encrypt + Certbot |
| Reverse proxy | ALB or Nginx | Nginx |

### 2.2 Settings & process management

- **Settings module:** `DJANGO_SETTINGS_MODULE=config.settings.prod`
  (`DEBUG=False`; HSTS, SSL redirect, secure cookies, XSS/nosniff already
  enforced in `config/settings/prod.py`).
- **App server:** `gunicorn` (pinned in `backend/requirements/prod.txt`) —
  **not** `runserver`. Static assets served via `whitenoise` (also pinned) or a
  CDN.
- **Background workers:** run `celery -A config.celery worker`,
  `celery -A config.celery beat` (DatabaseScheduler), and `manage.py start_mqtt`
  as managed services (systemd units or a production Compose file).
- **Migrations:** `manage.py migrate` runs as a release step before new app
  containers take traffic.
- **Frontend:** `npm run build` → static bundle served by Nginx/CDN (the Vite
  dev server is dev-only).

### 2.3 Required production secrets & env vars

Replace every placeholder from `.env.example` before any shared environment.
Non-negotiable:

| Var | Why |
|-----|-----|
| `DJANGO_SECRET_KEY` | Long random string; distinct from dev. |
| `JWT_SECRET_KEY` | Must differ from `DJANGO_SECRET_KEY`. |
| `FIELD_ENCRYPTION_KEY` | Fernet key encrypting DataSource / feed credentials at rest. Rotating it strands existing ciphertext — set once, back it up. |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` | Real hostnames only. |
| `DATABASE_URL` | Managed/hardened Postgres DSN. |
| `STORAGE_BACKEND=s3` (+ `AWS_*`) or `minio` | Object storage. |
| `MQTT_BROKER_PORT=8883` + `MQTT_*_B64` | mTLS only; **do not** set `MQTT_USERNAME`/`MQTT_PASSWORD` in prod. Generate/keep `MQTT_CA_KEY_B64` **offline** (HSM/secret manager), never beside app secrets. |
| `MQTT_ADMIN_PASSWORD` | Must match what Mosquitto was bootstrapped with. |
| `EMAIL_*` | Real SMTP/SES backend (not the console backend). |

Store secrets in a manager (AWS Secrets Manager / SSM, or Vault) — never in the
repo or a committed `.env`.

### 2.4 TLS, storage, backups

- TLS termination at ALB/Nginx; HSTS is already on in `prod.py`.
- All file storage goes through `django-storages` — only env vars change between
  S3 and MinIO.
- Postgres + object-storage **at-rest encryption** and automated **backups** must
  be enabled (this is also a Sprint 35 security-review gate).

### Production readiness — open items

These artifacts do **not** exist yet and are the concrete scope of a production
bring-up. Each is a checklist item, not a solved problem:

- ⛔ **Production Compose / systemd units** — `docker-compose.yml` is dev-shaped
  (`runserver`, exposed ports, dev creds). SPEC §7 says it is the *basis* for a
  prod file; that prod file/units don't exist.
- ⛔ **Nginx reverse-proxy config** — SPEC's project structure lists
  `infrastructure/nginx/`, but neither `infrastructure/` nor any nginx config is
  in the repo.
- ⛔ **Frontend build & static serving pipeline** (Vite build → whitenoise/CDN).
- ⛔ **CI/CD deploy pipeline** — CI runs lint+tests (Sprint 0); there is no
  deploy/release automation.
- ⛔ **Secrets management wiring** (Secrets Manager / SSM / Vault).
- ⛔ **Production MQTT PKI runbook** — offline CA generation, backend client-cert
  issuance, rotation. (Cert-expiry *alerting* exists — Sprint 23.)
- ⛔ **DB backups / restore drill, at-rest encryption verification** (Sprint 35 gate).
- ⛔ **Monitoring / health checks / log aggregation / alerting.**
- ⛔ **First-deploy runbook** (release order, migration step, smoke verification,
  rollback).

---

## Where deployment sits in the plan

There is currently **no dedicated production-deployment sprint in `ROADMAP.md`.**
The only production-adjacent items are:

- **Sprint 0** — created the split settings including `config.settings.prod` and
  `backend/requirements/prod.txt` (gunicorn, whitenoise). Infrastructure/CI for
  *dev* only.
- **Sprint 35** — a B3-readiness *security review* (at-rest encryption
  verification, NDB runbook, PIA, pen-test scoping) that references a
  "deployment guide" — i.e. this document — but is a gate, not a bring-up.
- **Phase 7 (Polish & Scale)** — CDN, read replicas, query optimisation — all
  *post-launch* scaling, not initial deployment.

**Recommendation:** insert a **"Production Environment Bring-up"** sprint now —
ahead of Sprint 34 — to deliver the ⛔ items above and get a real (staging-first)
environment running against live-shaped infrastructure. Deploying early surfaces
production-only classes of bug (TLS/mTLS, S3 vs MinIO signed URLs, SES
deliverability, static serving, migration ordering, secret wiring) while there's
still runway to fix them cheaply — rather than discovering them at the Sprint 35
security gate or at go-live.
