# Orbit — Buildable Core (Python)

The runnable heart of the Orbit rotating social club: the **rotation engine**,
domain models, an in-memory service layer, a test suite, and a multi-cycle demo.

> **Zero dependencies.** Pure Python standard library. Runs on Python 3.10+.
> Nothing to `pip install` to build, test, or run the demo.

This implements the design in the planning docs one level up (`../01`–`../09`).
The engine and services map 1:1 to `../04_App_Plan.md` (algorithm),
`../05_Requirements.md` (FR-IDs in the code comments), and
`../07_Database_Design.md` (models mirror the tables).

---

## Layout

```
code/
├── pyproject.toml                 # packaging + tool config (no runtime deps)
├── README.md                      # this file
├── Dockerfile                     # container image (no pip installs)
├── docker-compose.yml             # one-command self-hosted run
├── .dockerignore
├── migrations/
│   ├── 0001_init.sql              # production PostgreSQL schema (doc 07)
│   └── 0001_init_rollback.sql
├── orbit/
│   ├── __init__.py
│   ├── demo.py                    # runnable multi-cycle simulation
│   ├── api.py                     # entrypoint shim -> `python -m orbit.api`
│   ├── cli.py                     # entrypoint shim -> `python -m orbit.cli`
│   ├── domain/
│   │   ├── enums.py               # status/type enums
│   │   └── models.py              # dataclasses: Member, Group, Cycle, Event...
│   ├── matching/
│   │   └── rotation_engine.py     # ★ THE CRITICAL FILE — keep-50/swap-50
│   ├── web/
│   │   └── index.html             # single-file web UI (served at GET /)
│   └── services/
│       ├── repository.py          # in-memory store
│       ├── json_repository.py     # local-FILE persistence (survives restarts)
│       ├── postgres_repository.py # PostgreSQL backend (the SQL plan)
│       ├── repository_factory.py  # picks Postgres (if DATABASE_URL) else JSON
│       ├── serialization.py       # domain <-> JSON helpers
│       ├── api.py                 # REST API + UI serving + token auth
│       ├── cli.py                 # terminal operator (argparse)
│       ├── club_service.py        # club + member registration + density gate
│       ├── matching_service.py    # cycle orchestration around the engine
│       ├── event_service.py       # events, rotating ownership, fallback
│       ├── reputation_service.py  # reliability score + streaks
│       └── health_service.py      # group-health assessment + at-risk flags
└── tests/
    ├── test_rotation_engine.py    # the engine's guarantees
    ├── test_services.py           # club/matching/events/reputation/health
    ├── test_persistence.py        # JSON save/reload round-trips
    ├── test_api.py                # REST routing (no socket needed)
    └── test_ui_sql_wiring.py      # auth, cycles-list, factory, availability
```

---

## Run the tests

From the `code/` directory:

```bash
python -m unittest discover -s tests -v
```

Or run a single suite:

```bash
python -m unittest tests.test_rotation_engine -v
python -m unittest tests.test_services -v
```

> On Windows, use `python` (Python 3.10+). No virtualenv or installs needed.

---

## Run the demo

From the `code/` directory:

```bash
python -m orbit.demo
```

It simulates a 16-member club over 4 biweekly cycles and prints, per cycle:
group formation (keep-50/swap-50), each group's event (owner-run **or** the
auto-run fallback when nobody hosts), attendance, and any at-risk groups the
Health Watcher would be nudged about — then a final reliability leaderboard.

---

## Run the REST API (zero dependencies)

From the `code/` directory:

```bash
python -m orbit.api                       # http://127.0.0.1:8080, store ./orbit.json
ORBIT_HOST=0.0.0.0 ORBIT_PORT=9000 ORBIT_DB=/data/orbit.json python -m orbit.api
```

Smoke test:
```bash
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/clubs -H 'Content-Type: application/json' \
     -d '{"name":"My Club","city":"Austin","min_density":6}'
```

State persists to a **local JSON file** (`JsonFileRepository`) by default — it
survives restarts with no database or cloud. To run on **PostgreSQL** (the SQL
plan), set `DATABASE_URL` and install the driver (see "Web UI" and "Production
database" below). See `../10_Deployment_And_Hosting.md` for **3 ways to host**
Orbit, all outside Amazon.

---

## Web UI (single file, no build)

The server ships a full operator UI at `orbit/web/index.html` and serves it at
`GET /`. Just start the API and open the root URL in a browser:

```bash
python -m orbit.api
# open http://127.0.0.1:8080/  in your browser
```

The UI covers the whole loop: create/select clubs, add members (with a live
density readout), create + run rotation cycles (keep-50/swap-50), view groups
and create events (owner-run or auto-fallback), and a health dashboard with
at-risk flags. It talks to the REST API via `fetch`; if you host the UI
separately, set the **API base** field in the header. If the API has a token
(below), enter it in the **Token** field.

## Auth (optional token)

Set `ORBIT_TOKEN` to require a token on all write endpoints (POST/PUT/PATCH/
DELETE). Reads stay open. The UI sends it as `X-Orbit-Token`; curl example:

```bash
ORBIT_TOKEN=s3cret python -m orbit.api
curl -X POST http://127.0.0.1:8080/clubs -H 'X-Orbit-Token: s3cret' \
     -H 'Content-Type: application/json' -d '{"name":"C","city":"Austin"}'
```

---

## Drive it from the terminal (CLI)

```bash
python -m orbit.cli club-create --name "My Club" --city Austin --min-density 6
python -m orbit.cli member-add --club <CLUB_ID> --name Sam --email sam@x.io --niche creatives --avail tue_pm
python -m orbit.cli cycle-create --club <CLUB_ID> --start 2026-01-06
python -m orbit.cli cycle-run --cycle <CYCLE_ID> --seed 1
python -m orbit.cli groups --cycle <CYCLE_ID>
python -m orbit.cli health --cycle <CYCLE_ID>
```

Everything is stored in `orbit.json` by default (override with `--db`).

---

## Production database (PostgreSQL — the SQL plan)

Orbit auto-selects storage via `orbit/services/repository_factory.py`:
- **No `DATABASE_URL`** → local JSON file (default, zero deps).
- **`DATABASE_URL` set + `psycopg` installed** → `PostgresRepository` against
  the schema in `migrations/0001_init.sql`. If the driver is missing it prints
  a warning and falls back to JSON so the app still runs.

```bash
# 1. apply the schema (any Postgres 13+, self-hosted or managed)
psql "$DATABASE_URL" -f migrations/0001_init.sql
# 2. install the driver
pip install "psycopg[binary]>=3.1"
# 3. run against Postgres
DATABASE_URL=postgres://user:pass@host:5432/orbit python -m orbit.api
```

The Postgres repo exposes the **same method names** as the JSON/in-memory
repos, so services and the API are unchanged. Because services mutate domain
objects in place, the Postgres repo uses an identity map and a `flush()` that
the API calls at the end of each write request.

---

## What the rotation engine guarantees (and where it's tested)

| Guarantee | Where |
|-----------|-------|
| Groups sized 6–8 (`TARGET_MIN`..`TARGET_MAX`) | `test_group_sizes_within_bounds` |
| Keeps ~50% of a prior group (continuity/bonds) | `test_keeps_about_half_of_prior_group` |
| Fills with **haven't-met** members (anti-clique) | `test_prefers_havent_met_members_when_filling` |
| Never groups a **blocked** pair (safety) | `test_blocked_pair_never_grouped_together` |
| Splits by geographic **area** | `test_members_split_by_area` |
| **Fair owner** — not last cycle's owner | `test_owner_is_not_previous_owner_when_avoidable` |
| **Deterministic** given a seed | `test_same_seed_same_result` |
| **Pure** — never mutates its inputs | `test_does_not_mutate_inputs` |

The engine (`orbit/matching/rotation_engine.py`) is a **pure function**: it takes
`RotationInput` (plain snapshots + history) and returns a `RotationProposal`.
It performs no I/O and mutates nothing, which is why it is trivially testable
and reviewable by a human Rotation Steward before a proposal is committed.

---

## How this maps to the full architecture

This package is the **domain + application core** from `../04_App_Plan.md` §7.
To grow it into the full product:

1. **Swap the repository.** Replace `InMemoryRepository` with a
   PostgreSQL-backed implementation (schema in `../07_Database_Design.md`) that
   exposes the same method names. No service or engine code changes.
2. **Wrap services in an API.** Put a REST/GraphQL layer (FastAPI/NestJS) in
   front of the services (`../09_File_Manifest.md` shows the full backend tree).
3. **Add workers.** Schedule `MatchingService.generate_proposal` on the cycle
   cron and reminders/health as background jobs.
4. **Upgrade matching (V1).** `rotation_engine._fill_group` uses a simple,
   explainable greedy score today; replace it with the weighted scorer
   (`scoring.ts` equivalent) without changing the public interface.

---

## Notes & limitations (honest)

- This is the **buildable core**, not the whole app — no mobile/web UI, no real
  DB, no payments integration here (those are scaffolded in the file manifest,
  `../09_File_Manifest.md`).
- Ownership "acceptance" in `EventService.offer_ownership` is **simulated** via a
  reliability gate (`>= 50`) so the loop is runnable end-to-end; in production
  this is a real member action.
- The demo uses fixed seeds, so its output is deterministic and stable.
- **Not executed here:** these files were written but not run in this session
  (per instruction not to run anything locally). Run the two commands above to
  verify on your machine.
