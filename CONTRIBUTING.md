# Fieldmouse — Contributing Guide

> Development workflow, standards, and process for the Fieldmouse platform.
> Read this before writing any code.

---

## Prerequisites

Before setting up the project, ensure you have:

- Docker Desktop (latest stable)
- Node.js 20+ and npm
- Python 3.12+
- Git
- A copy of `.env` based on `.env.example` — ask a team member for values

> **Note on external services:** Local development uses Mosquitto (MQTT) and MinIO (object storage) running in Docker — no AWS account needed to run the platform locally. Email in dev is handled by a local SMTP stub (configured in `.env.example`). AWS credentials are only needed if deploying to AWS.

---

## Local Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-org/fieldmouse.git
cd fieldmouse

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env with your local values

# 3. Start all services
docker-compose up -d

# 4. Run database migrations
docker-compose exec backend python manage.py migrate

# 5. Create a Fieldmouse Admin user for local development
docker-compose exec backend python manage.py createsuperuser

# 6. Start the React frontend dev server
cd frontend && npm install && npm run dev
```

The following services will be running:

| Service | URL / Port |
|---------|-----------|
| Django API | http://localhost:8000 |
| React frontend | http://localhost:5173 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| Mosquitto (MQTT) | localhost:1883 |
| MinIO (object storage) | http://localhost:9000 (API) / http://localhost:9001 (console) |
| Celery worker | (background, check logs) |
| Celery beat | (background, check logs) |

To view Celery logs:
```bash
docker-compose logs -f celery_worker
docker-compose logs -f celery_beat
```

---

## Project Structure

```
fieldmouse/
├── backend/
│   ├── apps/
│   │   ├── accounts/        # Auth, tenants, users, notification groups
│   │   ├── devices/         # Device types, devices, health, streams
│   │   ├── ingestion/       # MQTT ingestion, topic router, 3rd party polling
│   │   ├── readings/        # StreamReadings, CSV export
│   │   ├── rules/           # Rule builder, evaluation engine, audit trail
│   │   ├── alerts/          # Alert generation and management
│   │   ├── dashboards/      # Dashboard and widget configuration
│   │   └── notifications/   # In-app, email, SMS, push delivery
│   ├── config/
│   │   ├── settings/
│   │   │   ├── base.py
│   │   │   ├── dev.py
│   │   │   ├── prod.py
│   │   │   └── test.py
│   └── manage.py
├── frontend/
│   ├── src/
│   │   ├── components/      # Reusable UI components
│   │   ├── pages/           # Page-level components (route targets)
│   │   ├── layouts/         # Layout wrappers (sidebar, topbar)
│   │   ├── hooks/           # Custom React hooks
│   │   ├── services/        # API client, auth service
│   │   └── theme/           # Semantic colour tokens, typography
│   ├── index.html
│   └── vite.config.js
├── mobile/                  # React Native app — Phase 6
├── SPEC.md                  # Full project specification — read before any task
├── ROADMAP.md               # Sprint-by-sprint development plan
├── ERD.md                   # Entity relationship diagram
├── CLAUDE.md                # Claude Code instructions
└── CONTRIBUTING.md          # This file
```

---

## Branching Strategy

All work happens on branches off `main`.

| Branch type | Format | Example |
|-------------|--------|---------|
| Feature | `feature/short-description` | `feature/rule-evaluation-engine` |
| Bug fix | `fix/short-description` | `fix/alert-duplicate-on-concurrent-read` |
| Sprint setup | `sprint/N-description` | `sprint/16-rule-builder-frontend` |
| Hotfix | `hotfix/short-description` | `hotfix/mqtt-connection-drop` |

**Rules:**
- Never commit directly to `main`
- Every change goes through a pull request — no exceptions
- Squash merge to `main` (keeps history clean)
- Delete the branch after merge

---

## Development Workflow

For every sprint, follow this sequence:

```
1. Create branch off main
2. Build backend: model → migration → serializer → view → URL → tests
3. Confirm backend tests pass before touching frontend
4. Build frontend: API service → hooks → components → page
5. Manual smoke test the complete feature
6. Open PR → CI must pass → code review → merge
7. Confirm Definition of Done from ROADMAP.md is met before closing the sprint
```

### Starting a new feature

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
```

### Keeping your branch up to date

```bash
git fetch origin
git rebase origin/main
```

Prefer rebase over merge to keep history linear.

---

## Running Tests

### Backend

```bash
# Run all tests with coverage
docker-compose exec backend pytest --cov=apps/ -v

# Run tests for a specific app
docker-compose exec backend pytest apps/rules/ -v

# Run a specific test file
docker-compose exec backend pytest apps/rules/tests/test_evaluation.py -v

# Run a specific test
docker-compose exec backend pytest apps/rules/tests/test_evaluation.py::test_rule_fires_on_false_to_true -v

# Check coverage report
docker-compose exec backend pytest --cov=apps/ --cov-report=html
# Open htmlcov/index.html in browser
```

Minimum coverage target: **80% per Django app.**

> CI runs the **full test suite** on every PR — not just tests related to the current sprint. A PR cannot be merged if any test from any sprint fails.

### Frontend

```bash
cd frontend

# Run all tests
npm test -- --watchAll=false

# Run tests for a specific component
npm test -- --watchAll=false --testPathPattern=RuleBuilder

# Run with coverage
npm test -- --watchAll=false --coverage
```

### Linting

```bash
# Backend
docker-compose exec backend flake8 apps/
docker-compose exec backend isort --check-only apps/

# Auto-fix isort
docker-compose exec backend isort apps/

# Frontend
cd frontend && npx eslint src/
cd frontend && npx prettier --check src/

# Auto-fix
cd frontend && npx prettier --write src/
```

---

## Writing Tests

### Backend — what to test for every endpoint

Every API endpoint must have tests for:

1. **Happy path** — correct request returns correct response
2. **Authentication** — unauthenticated request returns 401
3. **Cross-tenant isolation** — Tenant A user cannot access Tenant B data (returns 403 or 404)
4. **Role permissions** — where applicable, lower roles are rejected (e.g. View-Only cannot write)
5. **Validation** — invalid input returns 400 with meaningful error

```python
# Example test structure
class TestRuleCreateView:
    def test_create_rule_success(self, tenant_admin_client, tenant):
        """Tenant Admin can create a rule."""
        ...

    def test_create_rule_unauthenticated(self, api_client):
        """Unauthenticated request returns 401."""
        ...

    def test_create_rule_cross_tenant_denied(self, other_tenant_admin_client, tenant):
        """Tenant Admin cannot create rules in another tenant."""
        ...

    def test_create_rule_operator_denied(self, operator_client, tenant):
        """Operator cannot create rules."""
        ...

    def test_create_rule_invalid_condition(self, tenant_admin_client, tenant):
        """Invalid condition type returns 400."""
        ...
```

### Frontend — what to test per component

1. **Renders correctly** — component renders without crashing with required props
2. **Loading state** — shows loading indicator while data fetches
3. **Error state** — shows error message when API call fails
4. **Empty state** — shows empty state message when data is empty
5. **User interactions** — button clicks, form submissions trigger correct behaviour

---

## Pull Request Process

1. **Before opening a PR:**
   - All tests pass locally
   - Linting passes with no errors
   - You have done a manual smoke test of the feature
   - The ROADMAP.md Definition of Done for this sprint item is met

2. **PR description must include:**
   - What this PR does (1–3 sentences)
   - Which sprint/ROADMAP item it addresses
   - How to test it manually (steps)
   - Any decisions made that differ from SPEC.md (flag these — SPEC.md may need updating)

3. **PR title format** (Conventional Commits):
   - `feat: add rule evaluation engine`
   - `fix: prevent duplicate alert on concurrent evaluation`
   - `test: add cross-tenant isolation tests for rules API`
   - `docs: update ERD with RuleStreamIndex`

4. **CI must be green** — PRs with failing CI are not reviewed until fixed.

5. **After merge** — delete the feature branch.

---

## Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

[optional body — explain why, not what]
```

Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `perf`

```bash
# Examples
git commit -m "feat: add staleness condition evaluation to Celery beat task"
git commit -m "fix: Redis flag not cleared when rule condition transitions to false"
git commit -m "test: add concurrent evaluation race condition test for rules"
git commit -m "docs: update ERD.md to reflect RuleConditionGroup split"
```

---

## Code Standards Summary

Full standards are in SPEC.md Section 7. Key rules:

### Backend
- PEP 8 — enforced by flake8
- `isort` for import ordering
- Type hints on all function signatures
- Docstrings on all functions, classes, and methods
- Use `logging` module — never `print()`
- Filter all querysets by `tenant_id` — no exceptions
- Use `select_related` / `prefetch_related` — avoid N+1 queries
- Use Celery for async work — never block a request with slow operations

### Frontend
- Functional components + hooks only — no class components
- React Query (TanStack Query) for all data fetching
- React Router for navigation
- Semantic colour tokens only — no hardcoded hex values
- Handle loading, error, and empty states on every page and component
- ESLint (Airbnb config) + Prettier — enforced by CI

---

## Definition of Done (Sprint Level)

A sprint is complete when **all** of the following are true:

- [ ] All backend tests pass (`pytest` with no failures) — this means the **full** test suite, including every test from every previous sprint
- [ ] All frontend tests pass (`npm test` with no failures) — full suite, all sprints
- [ ] Coverage is above 80% on any new Django app code
- [ ] Linting passes on backend and frontend with no errors
- [ ] At least one manual smoke test has been performed
- [ ] Cross-tenant isolation confirmed for any new endpoints
- [ ] The specific DoD items from ROADMAP.md for this sprint are met
- [ ] PR is merged to `main`
- [ ] Any SPEC.md deviations are documented and SPEC.md updated if needed

### Regression Rule

No test from a previous sprint may be broken, disabled, skipped, or deleted. If new work causes an existing test to fail, the **code must be fixed** — not the test. The only exception is when the spec has genuinely changed (e.g. a business rule was revised), in which case SPEC.md must be updated and the change discussed before any test is modified.

---

## Environment Variables

All secrets and configuration live in `.env`. Never commit this file.

See `.env.example` for the full list of required variables with descriptions.

Key variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `MQTT_BROKER_HOST` | MQTT broker hostname (e.g. `localhost` or AWS IoT Core endpoint) |
| `MQTT_BROKER_PORT` | MQTT broker port (default `1883`, or `8883` for TLS) |
| `MQTT_USERNAME` | MQTT broker username |
| `MQTT_PASSWORD` | MQTT broker password |
| `STORAGE_BACKEND` | `s3` for AWS S3 or `minio` for self-hosted MinIO |
| `AWS_ACCESS_KEY_ID` | AWS or MinIO access key |
| `AWS_SECRET_ACCESS_KEY` | AWS or MinIO secret key |
| `AWS_STORAGE_BUCKET_NAME` | S3 bucket or MinIO bucket name |
| `AWS_S3_ENDPOINT_URL` | Leave blank for AWS S3; set to MinIO URL (e.g. `http://minio:9000`) for self-hosted |
| `EMAIL_BACKEND` | Django email backend class (e.g. `django.core.mail.backends.smtp.EmailBackend`) |
| `EMAIL_HOST` | SMTP server hostname |
| `EMAIL_PORT` | SMTP server port |
| `EMAIL_HOST_USER` | SMTP authentication username |
| `EMAIL_HOST_PASSWORD` | SMTP authentication password |
| `DEFAULT_FROM_EMAIL` | Sender address for all outbound email |
| `JWT_SECRET_KEY` | Secret for JWT signing |
| `ENCRYPTION_KEY` | Key for encrypting DataSource credentials |

---

## Getting Help

- Check `SPEC.md` first — most questions are answered there
- Check `ROADMAP.md` for current sprint scope
- If something contradicts `SPEC.md`, raise it before building — don't work around it
- If you're unsure whether a decision belongs in Phase 1 or later, check Section 8 of SPEC.md
