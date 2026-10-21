# Load test

`locustfile.py` simulates members using the workspace: sign-in once, then home, tasks, room messages, notifications, search and the timer. AI calls are off unless `FLOBRAIN_ASK=1`.

Run it against staging with a dedicated load-test org, never production:

```bash
pip install locust
FLOBRAIN_EMAIL=loadtest@example.com FLOBRAIN_PASSWORD=... FLOBRAIN_ORG=<org uuid> \
  locust -f deploy/loadtest/locustfile.py --host https://staging-api.example.com \
  --users 200 --spawn-rate 10 --run-time 15m --headless --csv loadtest
```

What to watch, and the targets for the first external customers (bootcamps and SMBs, a few hundred people per org):

| Measure | Target |
|---|---|
| p95 for reads (tasks, messages, notifications) | under 400 ms |
| p95 for search | under 1 s |
| Error rate | under 0.5 % |
| Database CPU | under 60 % sustained |
| Job queue lag (`jobs` rows older than a minute) | none |

All users share one account in this script, so it exercises the API and database, not per-user caches. For a realistic mix, create one user per simulated person and pass them in a CSV.

Results so far: `RESULTS.md` (a local baseline from 2026-10-21; staging still to do).
