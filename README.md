# That Place — IoT Monitoring, Control & Automation Platform

A B2B IoT platform for monitoring devices, controlling field hardware, and automating responses to sensor data — built for local councils, agriculture, and industry.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Node.js 20+](https://nodejs.org/)
- [Python 3.12+](https://www.python.org/)
- [Git](https://git-scm.com/)

---

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd that-place
   ```

2. **Copy the example environment file and fill in any values you need to change**
   ```bash
   cp .env.example .env
   ```

3. **Start all services**
   ```bash
   docker-compose up -d
   ```

4. **Run database migrations**
   ```bash
   docker-compose exec backend python manage.py migrate
   ```

5. **Create a superuser**
   ```bash
   docker-compose exec backend python manage.py createsuperuser
   ```

6. **Start the frontend dev server**
   ```bash
   cd frontend && npm install && npm run dev
   ```

---

## Services

| Service | URL | Notes |
|---------|-----|-------|
| Django API | http://localhost:8000 | DRF + SimpleJWT |
| React web app | http://localhost:5173 | Vite dev server |
| PostgreSQL | localhost:5432 | DB: `that_place`, user: `that_place` |
| Redis | localhost:6379 | Celery broker + result backend |
| Mosquitto MQTT | localhost:1883 | MQTT broker for device telemetry |
| MinIO API | http://localhost:9000 | S3-compatible local object storage |
| MinIO console | http://localhost:9001 | Web UI — login with MinIO credentials from `.env` |

---

## Running Tests

**Backend tests (pytest):**
```bash
docker-compose exec backend pytest --cov=apps/ -v
```

**Run a specific test file:**
```bash
docker-compose exec backend pytest apps/rules/tests/test_evaluation.py -v
```

**Frontend tests (Jest + React Testing Library):**
```bash
cd frontend && npm test -- --watchAll=false
```

**Frontend test coverage:**
```bash
cd frontend && npm run test:coverage
```

---

## Linting

**Backend:**
```bash
docker-compose exec backend flake8 apps/
docker-compose exec backend isort --check-only apps/
```

**Frontend:**
```bash
cd frontend && npx eslint src/
```

---

## Further Documentation

- [`SPEC.md`](./SPEC.md) — Full project specification, data model, API patterns, and feature acceptance criteria
- [`ROADMAP.md`](./ROADMAP.md) — 25-sprint delivery plan across Phases 1–5
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Branching strategy, PR process, and development workflow
- [`CLAUDE.md`](./CLAUDE.md) — Coding conventions for Claude Code sessions
