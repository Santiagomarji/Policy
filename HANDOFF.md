# HANDOFF — Orbit Rotating Social Club

Hi krew 👋 — this is a complete, self-contained app. **You do not need to install
anything except Python** (3.10 or newer). No pip packages, no database, no cloud
account. It runs on your machine as-is.

---

## What Orbit is (30 seconds)

A social club app engineered so the club *can't die*: members join, get matched
into small groups (6–8), and the groups **partially rotate** each cycle (keep
~half, meet ~half new people). Ownership rotates and the app auto-runs a
fallback event if nobody hosts — so it never depends on one organizer.

Everything is in this package:
- **Planning docs** (`README.md` + `01`–`13`) — research, plan, DB design, etc.
- **`code/`** — the actual runnable app.

---

## Run it in 3 steps

Open a terminal **in the `code/` folder** and:

**1. Check the code is healthy (optional, ~2 sec):**
```
python -m compileall orbit tests
```

**2. Run the tests (proves it works, ~5 sec):**
```
python -m unittest discover -s tests -v
```
You should see a wall of `ok` and `OK` at the end.

**3. Start the app + web UI:**
```
python -m orbit.api
```
Then open **http://127.0.0.1:8080/** in your browser. You'll get an operator
console — create a club, add members, run a rotation, see groups, and try the
"My Orbit" member view.

> On Windows use `python`; on Mac/Linux you may need `python3`.

---

## Other ways to run it

**See a simulation without the UI** (populates a demo club over 4 cycles):
```
python -m orbit.demo
```

**Drive it from the terminal (no browser):**
```
python -m orbit.cli club-create --name "My Club" --city Austin --min-density 6
python -m orbit.cli member-add --club <CLUB_ID> --name Sam --email sam@x.io --avail tue_pm
python -m orbit.cli cycle-create --club <CLUB_ID> --start 2026-01-06
python -m orbit.cli cycle-run --cycle <CYCLE_ID> --seed 1
python -m orbit.cli groups --cycle <CYCLE_ID>
```

---

## Where your data goes

By default the app saves everything to a local file **`orbit.json`** in whatever
folder you run it from. Delete that file to start fresh. Nothing leaves your
machine.

---

## If you want to host it for real (later)

- **Docker:** `docker compose up` from `code/` (see `../10_Deployment_And_Hosting.md`).
- **PostgreSQL** instead of the JSON file: apply `code/migrations/0001_init.sql`
  to a Postgres DB, `pip install "psycopg[binary]"`, then set
  `DATABASE_URL=...` before `python -m orbit.api`.
- **Auth:** set `ORBIT_TOKEN=somesecret` to require a token on write actions.

Full 3-way hosting guide (all outside Amazon): `../10_Deployment_And_Hosting.md`.

---

## Heads-up / known notes

- **Not yet run end-to-end by me** — the code compiles cleanly and is
  self-reviewed, but please run step 2 (the tests) first; if anything is red,
  send me the output and I'll fix it fast.
- **No mobile app** — this is the backend + web UI. The mobile app is only
  planned (see `../09_File_Manifest.md`).
- The web UI is an **operator/admin tool** — fine for running the club; it's not
  a public member signup page yet.

---

## Questions?

Start with the top-level `README.md` (it indexes all 13 docs). The most useful
for you are probably:
- `code/README.md` — how the code is structured + all run commands
- `11_Customer_Journeys.md` — what the member experience looks like
- `10_Deployment_And_Hosting.md` — hosting options
