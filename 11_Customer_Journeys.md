# 11 — Customer Journeys & Experience Audit

*This documents the actual customer experience end-to-end, the friction points
found during an audit, and how each was fixed. It pairs with the E2E tests in
`code/tests/test_journeys.py` and `code/tests/test_edge_cases.py`.*

---

## Two customers, two journeys

Orbit has two distinct users. Earlier the whole product was **operator-facing**;
the member — the real customer — was blind after joining. That was the biggest
experience gap and is now fixed with a member-facing API + UI.

| Customer | What they do | Where |
|----------|-------------|-------|
| **Member** | join → see my group → see my next event → RSVP → attend → build connections → stay safe | `/members/*` API + "My Orbit" UI card |
| **Operator** | create club → add members/venue → run rotation → run events → watch health | `/clubs`, `/cycles`, `/groups` API + operator UI |

---

## The member journey (the smooth path)

1. **Join** — operator (or a signup flow) registers the member with availability + niche.
2. **Get placed** — when a cycle is committed, the rotation engine places the member in a group (keep ~50% / swap ~50%).
3. **See my group** — `GET /members/{id}/group` returns the group + groupmates. *No more blindness.*
4. **See my next event** — `GET /members/{id}/upcoming` returns the soonest event.
5. **RSVP myself** — `POST /members/{id}/rsvp` RSVPs to my next event without me needing to know the event id. If there's no event yet, a clear **409** ("no upcoming event") instead of a confusing failure.
6. **Attend** — attendance lifts my `reliability_score` and `current_streak`.
7. **See my connections** — `GET /members/{id}/connections` shows everyone I've met across cycles — the emotional payoff of rotation.
8. **Stay safe** — `POST /members/{id}/block` lets me block someone; the matcher will never group us again.

Tested end-to-end in `test_journeys.py::TestJourneyA_NewMemberFirstCycle`.

---

## Friction points found in the audit → and the fix

| # | Friction (customer couldn't...) | Fix |
|---|----------------------------------|-----|
| 1 | see their own group after joining | `GET /members/{id}/group` + "My Orbit" UI card |
| 2 | see their next event | `GET /members/{id}/upcoming` |
| 3 | RSVP without knowing the event id | `POST /members/{id}/rsvp` (self-RSVP to next event) |
| 4 | block/report anyone (safety invisible) | `POST /members/{id}/block` + UI block control |
| 5 | see who they've met (rotation payoff hidden) | `GET /members/{id}/connections` |
| 6 | fetch a single group/event to refresh | `GET /groups/{id}`, `GET /events/{id}` (+ rsvps, going_count) |
| 7 | operator couldn't add the partner venue (fallback broke) | `POST/GET /clubs/{id}/venues` |
| 8 | operator couldn't list a group's events | `GET /groups/{id}/events` |
| 9 | operator couldn't list cycles to pick one | `GET /clubs/{id}/cycles` (added earlier) |
| 10 | UI had no member perspective at all | "My Orbit (member view)" card: profile, group, next event + RSVP, connections, block, with loading/empty states |

---

## Edge cases handled (so the experience never breaks)

Covered in `test_edge_cases.py`:

- **Malformed input** → clean `400` (bad date, missing name/email, non-numeric lat/lng).
- **Unknown ids** → clean `404` across clubs/cycles/groups/events/members/venues (never a stack trace).
- **Empty states** → a brand-new member sees `group: null`, `event: null`, `connections: []` (never an error), and the UI shows friendly "not placed yet / no event yet / connections grow every cycle" messages.
- **Self-RSVP with no event** → `409` with a clear message.
- **Too few members** → rotation places nobody (`groups: []`) instead of forming a broken group.
- **Everyone flakes** → the group is flagged `at_risk` for the Health Watcher, and flakers' reliability drops.
- **Nobody hosts** → an auto-run **fallback event** at the partner venue means the member is *never* stranded (Journey C).
- **Blocked pair** → never grouped together across many cycles (Journey D).

---

## Test inventory

| File | What it proves |
|------|----------------|
| `test_rotation_engine.py` | the matching guarantees (sizing, keep-50/swap-50, anti-clique, blocks, fair owner, determinism, purity) |
| `test_services.py` | club/matching/events/reputation/health service logic |
| `test_persistence.py` | JSON save/reload round-trips (durability) |
| `test_api.py` | REST routing + full operator flow |
| `test_ui_sql_wiring.py` | auth, cycles list, availability normalization, repo factory |
| `test_journeys.py` | 5 realistic multi-cycle **customer journeys** (A–E) |
| `test_edge_cases.py` | malformed input, empty states, unplaced, all-flake, member-service units |

Run them all from `code/`:
```bash
python -m unittest discover -s tests -v
```

---

## UX principles applied (to make it the smoothest experience)

- **Never a dead end** — every empty state has a friendly message and a next step, not a blank screen or an error.
- **Self-service** — the member does the common things (see group, RSVP, block) without an operator.
- **Clear errors** — `400` for bad input, `404` for unknown, `409` for "nothing to RSVP to" — each with a human-readable message the UI surfaces as a toast.
- **The payoff is visible** — connections accumulated across cycles are shown, so the member *feels* the value of rotation.
- **Safety is one tap** — blocking is a first-class member action, enforced by the matcher.
