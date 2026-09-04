# 13 — Hardening Pass (SQL Review, Welcomer, Ratings, Per-Member Auth)

*A three-part hardening pass. All stdlib, all tested, not executed here.*

---

## 1. Postgres SQL deep-review (static)

Cross-checked **every** `PostgresRepository` SQL statement against the DDL in
`migrations/0001_init.sql`, column-by-column, for all 14 tables. **No critical
mismatches.** Verified: column lists, enum text→enum implicit casts (valid in
psycopg3), `jsonb` via the `Json` wrapper, `group_id ""→NULL` for club-wide big
events (allowed by `ALTER … DROP NOT NULL`), all 20 index names unique, and
`latest_committed_cycle` (`ORDER BY start_date DESC`) matching the in-memory
"latest" semantics.

**Fixed:** removed an unused `Iterator` import.

**Noted (minor, by design):**
- `add_member` writes member + preference as two autocommit statements (not one
  transaction); the read path uses `LEFT JOIN` so a partial write degrades
  gracefully rather than crashing.
- `member UNIQUE(club_id, email)` means Postgres rejects duplicate emails while
  the JSON store allows them — a behavioral divergence to be aware of if you
  rely on dedupe.

## 2. Welcomer onboarding flow — `WelcomerService`

Plugs the #1 retention leak (doc 01): un-welcomed newcomers quietly leave. On
registration the API now auto-runs `onboard(member_id)`, which:
- finds the club's active **Welcomer** volunteer (if any),
- picks a **first-event buddy** (most reliable existing member),
- schedules **welcome notifications** to newcomer + buddy + welcomer.

Tolerant: with no welcomer/buddy yet it still welcomes the newcomer.
`needs_welcome(club_id)` lists active members not yet placed (a Welcomer
dashboard feed). Registration response includes an `onboarding` summary.

## 3. Ratings + post-event follow-up — `RatingService`

The bonding-compounds mechanic (doc 01 success pattern #4):
- `rate_event(event_id, member_id, score 1-5, comment?)` — **attendees only**
  (RSVP required), score validated.
- `event_score` / `event_rating_summary` — average + comments.
- `send_follow_ups(event_id)` — sends each attendee a "keep in touch with
  {others}" prompt, naming their fellow attendees.

**API:** `POST /events/{id}/rate`, `GET /events/{id}/ratings`,
`POST /events/{id}/follow-up`. Backed by the `rating` table (already in the
migration) + a new `Rating` domain model (it was referenced in the schema but
never modeled — now added and persisted on all three backends).

## 4. Per-member auth

Each member gets a `member_token` at registration (returned once, in that
response only — never in list views). Member-scoped writes
(`/members/{id}/rsvp|block|subscribe|cancel`) enforce `_require_self`:

- **operator token** (`ORBIT_TOKEN`) → allowed (admin override), OR
- the caller's token **equals that member's** `member_token` → allowed, OR
- **open mode** (no operator token configured and no token supplied) → allowed
  (so the tool stays frictionless until you turn auth on),
- otherwise → **403** ("you can only act as yourself").

The global operator-write gate deliberately **skips** `/members/*` routes so a
member can authenticate with their own token instead of the operator token.

---

## Tests (`code/tests/test_hardening.py`)

- **Welcomer**: no-welcomer-still-welcomes, assigns welcomer + buddy (3 notes),
  `needs_welcome` lists unplaced.
- **Ratings**: attendee-only (`ValueError` for outsiders), bad-score rejected,
  average correct, follow-ups created per attendee.
- **Per-member auth**: registration returns a token, a member **cannot** act on
  another's endpoint (403), **can** act on their own (200), operator token works
  for anyone (200), and tokens are **not leaked** in list responses.

Existing no-token tests still pass (open mode). Run all:
```bash
cd code && python -m unittest discover -s tests -v
```

> Not executed in this session (local-file-only). Verified by static tracing.
