# CLAUDE.md — That Place Instructions for Claude Code

> This file is automatically read by Claude Code when working in this repository.

---

## Project Context

**Read `SPEC.md` before starting any task.** It contains the full project specification
including architecture decisions, features with acceptance criteria, the data model,
API patterns, and development rules.

That Place is a B2B IoT monitoring, control, and automation platform. Django + DRF backend,
React (Vite) web frontend (primary), React Native mobile app (Phase 6 only), PostgreSQL database.
Deployable on AWS (EC2 + S3 + SES, preferred) or any Linux server (MinIO + SMTP, self-hosted).

---

## How to Work in This Repo

### Before Starting Any Task
1. Read `SPEC.md` — especially the relevant feature section and the data model
2. Check existing code in the target app/directory before creating new files
3. Run the existing tests to confirm nothing is broken before you start
4. Identify which phase/milestone the task belongs to (SPEC.md Section 8)

### When Writing Backend Code
- Use Django REST Framework serializers and viewsets — no raw Django views
- All views require `IsAuthenticated` permission unless explicitly stated otherwise
- Use the data model from SPEC.md Section 4 — do not create new models without asking
- Follow the API URL patterns in SPEC.md Section 5 (`/api/v1/resource/`)
- Error responses must use the standard format: `{ "error": { "code": "...", "message": "..." } }`
- Use Celery for any async tasks (rule evaluation, notifications, polling)
- Type hints on all function signatures
- Filter all querysets by `tenant_id` — never return cross-tenant data

### When Writing Frontend Code (React Web)
- Functional components with hooks only — no class components
- Use React Query (TanStack Query) for all API data fetching and caching
- Navigation via React Router — check `frontend/src/` for existing route patterns
- Style with CSS modules or the project's existing styling approach — match existing patterns
- All colours must use semantic tokens from the theme (not hardcoded hex values)
- Handle loading, error, and empty states for every page/component
- Desktop-first — minimum supported width 1024px

### When Creating New Files
- Backend models: `backend/apps/{app_name}/models.py`
- Backend serializers: `backend/apps/{app_name}/serializers.py`
- Backend views: `backend/apps/{app_name}/views.py`
- Backend tests: `backend/apps/{app_name}/tests/test_{feature}.py`
- Frontend pages: `frontend/src/pages/{PageName}.jsx`
- Frontend components: `frontend/src/components/{ComponentName}.jsx`
- Frontend hooks: `frontend/src/hooks/use{HookName}.js`
- Frontend tests: alongside source files as `{ComponentName}.test.jsx`

### When Modifying Existing Code
- Do not change database migrations without explicit approval
- Preserve all existing tests — if refactoring, make sure tests still pass
- If you need to change the data model, update SPEC.md Section 4 as well
- Check for downstream effects — changing a serializer may break frontend expectations
- Codex will review your code when you're done
---

## Key Commands

```bash
# Start local development environment
docker-compose up -d

# Run backend tests
docker-compose exec backend pytest --cov=apps/ -v

# Run a specific backend test file
docker-compose exec backend pytest apps/rules/tests/test_evaluation.py -v

# Create new migration
docker-compose exec backend python manage.py makemigrations
docker-compose exec backend python manage.py migrate

# Django shell
docker-compose exec backend python manage.py shell_plus

# Lint backend
docker-compose exec backend flake8 apps/
docker-compose exec backend isort --check-only apps/

# Frontend — run dev server
cd frontend && npm run dev

# Frontend tests
cd frontend && npm test -- --watchAll=false

# Frontend lint
cd frontend && npx eslint src/
```

---

## Things to Never Do
- Never make git commits — always leave committing to the user
- Never commit `.env` files or any secrets/credentials
- Never bypass authentication on API endpoints
- Never allow Tenant A to access Tenant B's data — every queryset must be filtered by `tenant_id`
- Never use class-based React components
- Never use `print()` for logging — use Python's `logging` module
- Never store user-uploaded files on the local filesystem — use S3-compatible object storage (AWS S3 or MinIO depending on deployment)
- Never modify SPEC.md without asking first
- Never introduce a new pip/npm dependency without checking if an existing one solves the problem
- Never hardcode MQTT topic strings — use the registered pattern system
- Never evaluate rules inline in the ingestion path — always dispatch a Celery task
- Never delete, skip (`pytest.mark.skip` / `xit`), or weaken an existing test to make new code pass — fix the code instead. If the spec has genuinely changed, update SPEC.md first and discuss before touching the test.

---

## Things to Always Do
- Always run `flake8 apps/` and `isort --check-only apps/` inside Docker before considering a backend task complete — fix any errors before handing back, do not wait for CI to catch them
- Always run the full test suite (`docker-compose exec backend pytest --cov=apps/ -q` and `cd frontend && npm test -- --watchAll=false`) before considering a sprint complete — all tests must pass with no regressions
- Always write tests for new API endpoints (happy path + at least one permission/error case)
- Always use environment variables for all external service credentials, secrets, and configuration — never hardcode AWS or any provider-specific values
- Always validate input on both frontend (form validation) and backend (serializer validation)
- Always handle errors gracefully — show meaningful messages to the user
- Always filter querysets by `tenant_id` — no exceptions
- Always use `select_related` / `prefetch_related` to avoid N+1 queries
- Always add a docstring to new functions, classes, and components
- Always reference the relevant SPEC.md section when implementing a feature
- Always update `RuleStreamIndex` when a rule is created, edited, or deleted

---

## Data Isolation Rules (Critical)
Tenant A must never see Tenant B's data. Every queryset in every view must be
filtered by the requesting user's tenant. Specifically:

- Resolve tenant from `request.user` via their `TenantUser` record
- Filter all querysets: `queryset.filter(tenant_id=request.user.tenantuser.tenant_id)`
- That Place Admin accounts bypass tenant filtering but must never mix tenant data in responses
- Write a cross-tenant permission test for every endpoint that modifies data

---

## Reference Files
- `SPEC.md` — Full project specification (read this first, always)
- `backend/config/settings/base.py` — Django base settings
- `backend/config/settings/dev.py` — Local development overrides
- `backend/apps/accounts/models.py` — User, Tenant, TenantUser models
- `frontend/src/services/api.js` — Axios instance with auth interceptors
- `frontend/src/theme/colors.js` — Semantic colour tokens
- `docker-compose.yml` — Local dev environment
- `.env.example` — Required environment variables with descriptions

---

## Asking for Clarification

If a task is ambiguous or could conflict with SPEC.md, **stop and ask before proceeding.**
Always ask when:
- The task requires a new database model or entity not in SPEC.md Section 4
- The task requires a new external service or third-party dependency
- The acceptance criteria are unclear or contradictory
- The task could affect authentication, authorisation, or tenant data isolation
- The task involves the MQTT ingestion pipeline or rule evaluation engine
- You're unsure whether something belongs in Phase 1 vs a later phase
