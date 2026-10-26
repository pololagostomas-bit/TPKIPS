# Tunnel Recovery And Reception Reports Implementation Plan

> Execute inline with one coordinator; at most one bounded public/synthetic reviewer.

**Goal:** Recover only the reader tunnel autonomously on Linux, then make the reception indicator report searchable and reliably downloadable without blocking production.

**Architecture:** A standalone Python/systemd timer checks local app and current tunnel HTTPS independently, with failure threshold, startup grace, maintenance and restart budget. Reports retain their separate worker/SQLite snapshot and receive focused fixes after reproducing the failure.

**Stack:** Existing Python stdlib, Docker CLI, systemd, SQLite/openpyxl and vanilla JS/CSS. No AI, new frontend framework, daily mail or operating-data migration.

## Constraints

- Manual app remains frozen. Guard cannot restart app, Ubuntu, Docker, Windows or a manual container; only exact reader tunnel.
- Owner authorized one Ubuntu restart after WSL stopped responding. Do not generalize to automatic VM/host restarts.
- Reuse healthy tunnel, latest URL from current startup, HTTPS login + health validation; no stale URL reported as available.
- No recovery during local-app failure, Internet failure, access challenge, startup grace, maintenance or exhausted restart budget.
- Local service install is authorized; no merge or app deployment from this task. App/report code uses a new PR against approved main.
- No real emails, secrets, operating rows, Excel or private configuration published. Preserve unrelated dirty resilience work.

## Task 1: Linux Tunnel Supervisor

Files: infrastructure/deployment/tunnel_guard.py, triton-wms-tunnel-guard.service/.timer; tests/test_tunnel_guard.py; docs/home-tunnel-recovery.md.

- [x] RED/GREEN policy tests: healthy no restart; old-start URL ignored; consecutive failures; local/Internet/auth/rate failures; grace; maintenance; cooldown/budget; restart error; no application/manual/host commands.
- [x] Implement bounded probes, atomic private state and OS lock. Timer every60s, only one instance, no daily email or Codex dependency.
- [x] Recover authorized Ubuntu only; inspect current approved runtime, back up only changed service files, install reviewed guard and verify active timer/state/HTTPS. Never claim autonomy installed if WSL cannot be recovered.

## Task 2: Reception Indicator Report

Files: backend/services/report_jobs.py, reception report export/filter helpers,
scoped backend/app.py route, backend/wsgi.py and report_response.py streaming,
frontend/static/reception-report*.js/css and relevant tests/docs.

- [x] Reproduce indicator-report export independently from the existing large audit export. Measure queue/snapshot/build/download; do not assume slowness equals memory saturation.
- [x] RED/GREEN fixes with bounded background generation and current administrator permissions. Explicit BL search and matching export scope, no silent truncation or extra operational writes.
- [x] Verify double click/two users, filter change/stale response, failed job/retry, expired session, actual XLSX and mobile/desktop layouts using synthetic databases.
- [x] Full clean candidate tests and selected secret/diff checks.996tests pass,
  2existing skips;38focused Linux tests,4export and9report browser viewports.
  A660,000-event synthetic Linux audit completes within the existing worker limits.
- [ ] Publish/attach the scoped PR and save focused memory after publication.
  No app deployment or manual application changes.
