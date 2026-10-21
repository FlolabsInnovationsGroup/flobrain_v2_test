# Load test results

## 2026-10-21, local baseline (not staging)

The owner asked for the load test to be run last. There is no staging stack yet, so this run is on the build machine: **2 vCPUs** shared by everything (the API under gunicorn with 3 workers × 4 threads, PostgreSQL 16 with pgvector, and Locust itself), using the seeded demo org. Treat the numbers as a floor for "does anything fall over" and "which endpoint is heavy", not as production capacity.

**Setup:** 50 simulated members, ramping up at 5 a second, for 3 minutes. They all share one account. Each one signs in once, then does a weighted mix of home (`me/access` + tasks), room messages, notifications, search and the timer, waiting 2–8 seconds between actions.

| Endpoint | Before the fix: p50 / p95 (ms) | After the fix: p50 / p95 (ms) | Target p95 |
|---|---|---|---|
| `me/access` (every page) | 320 / 1,100 | **36 / 86** | 400 |
| tasks | 44 / 130 | 38 / 98 | 400 |
| room messages | 65 / 300 | 52 / 130 | 400 |
| notifications | 36 / 140 | 30 / 120 | 400 |
| search | 83 / 260 | 70 / 140 | 1,000 |
| timer start / stop | 40 / 95 | 29 / 70 | 400 |
| sign-in (once per user) | 8,900 / 15,000 | 8,000 / 14,000 | see below |

- **Errors:** 2 of 2,277 requests (0.09 %), both timer conflicts. Every simulated person shares one account, so they start and stop the same timer. This is expected with this script and is not a defect.
- **Fixed during the test:** `me/access` ran **114 queries**, one or two per permission key. It now evaluates all org-level permissions in 3 queries (`org_permissions`, 11 queries for the whole request), and a test keeps it equal to `can()` for every key and every kind of member. Its p95 dropped from 1.1 s to 86 ms.
- **Sign-in is CPU-bound on purpose.** Django 5.2 hashes passwords with PBKDF2 at 1,000,000 iterations, about 0.75 s of CPU per sign-in. With 50 people signing in at the same second on 2 vCPUs they queue, and the first-page calls made right after sign-in (the 50 `rooms` requests) waited behind them, p50 3.2 s. Warm, `rooms` answers in about 18 ms. Don't lower the hash cost. Size the API for sign-in bursts instead (a class or a team starting at the same minute): more API tasks, or more vCPU per task.

**Next:** rerun on staging with the targets in `README.md`, with 200 users and one account per simulated person.
