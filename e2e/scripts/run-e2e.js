#!/usr/bin/env node
// @ts-check
/**
 * One-command runner for the That Place Playwright E2E suite.
 *
 * Steps:
 *   1. Verify backend (:8000) and frontend (:5173) are reachable — fail fast
 *      with a helpful message naming the missing service.
 *   2. Reseed the deterministic fixture inside the backend container.
 *   3. Run `playwright test`, forwarding any extra CLI args.
 *
 * Used by `npm run e2e`. Anything after `npm run e2e --` is forwarded to
 * Playwright (e.g. `npm run e2e -- --project=chromium -g "rule fires"`).
 */
const { spawnSync } = require('child_process');
const http = require('http');

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://localhost:5173';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://localhost:8000';

function color(code, s) {
  return process.stdout.isTTY ? `\x1b[${code}m${s}\x1b[0m` : s;
}
const red = (s) => color('31', s);
const green = (s) => color('32', s);
const cyan = (s) => color('36', s);
const dim = (s) => color('2', s);

function fail(msg) {
  process.stderr.write(red(`\n✗ ${msg}\n`));
  process.exit(1);
}

function step(label) {
  process.stdout.write(cyan(`\n→ ${label}\n`));
}

function probe(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode || 0);
    });
    req.on('error', () => resolve(0));
    req.setTimeout(2000, () => { req.destroy(); resolve(0); });
  });
}

async function ensureUp(name, url, hint) {
  process.stdout.write(dim(`  ${name} ${url} `));
  const status = await probe(url);
  // Any HTTP response means the server is up; 0 = network error.
  if (status === 0) {
    process.stdout.write(red('unreachable\n'));
    fail(`${name} not reachable at ${url}.\n  ${hint}`);
  }
  process.stdout.write(green(`up (${status})\n`));
}

function run(cmd, args, opts = {}) {
  const result = spawnSync(cmd, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    ...opts,
  });
  return result.status ?? 1;
}

(async () => {
  step('Checking stack');
  await ensureUp('frontend', FRONTEND_URL, "Start it with 'docker-compose up -d' or 'cd frontend && npm run dev'.");
  await ensureUp('backend ', `${BACKEND_URL}/api/v1/auth/login/`, "Start it with 'docker-compose up -d'.");

  step('Seeding E2E fixture');
  const seedExit = run('docker-compose', [
    'exec', '-T', 'backend',
    'python', 'manage.py', 'seed_e2e',
  ]);
  if (seedExit !== 0) {
    fail('seed_e2e failed — see output above. Common causes: docker-compose not running, migrations pending.');
  }

  step('Running Playwright');
  const extraArgs = process.argv.slice(2);
  const playwrightExit = run('npx', ['playwright', 'test', ...extraArgs]);
  process.exit(playwrightExit);
})().catch((err) => {
  fail(err.stack || String(err));
});
