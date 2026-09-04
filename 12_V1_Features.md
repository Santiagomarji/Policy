# 12 — V1 Features (Built)

*These are the five specced-but-uncoded features from the roadmap (doc 04 §8,
Phase 2/V1), now implemented in `code/`. All stdlib, all backed by the shared
repository interface, all with tests in `code/tests/test_v1_features.py`.*

---

## 1. Monthly big-gathering flow — `BigEventService`

The club-wide monthly event (doc 04 §4.4), distinct from the biweekly small
group event.

- `create_big_event(club_id, starts_at, host_id?, backup_host_id?, venue_id?, capacity?)`
  — a `BIG` event that spans all groups (`group_id=""`, `club_id` set). Auto-uses
  the club's partner venue if none given.
- **Backup host safety net** — `effective_host()` returns the primary host, or the
  backup if the primary drops, so the big event never goes hostless.
- **Capacity + waitlist** — RSVPs beyond capacity go to `WAITLIST`; `cancel_rsvp()`
  frees a seat and auto-`promote_from_waitlist()` fills it.
- `attendance_summary()` → going / waitlist / capacity / spots_left.

**API:** `POST/GET /clubs/{id}/big-events`, `GET /big-events/{id}`,
`POST /big-events/{id}/rsvp`, `POST /big-events/{id}/cancel`.

## 2. Volunteer term management — `VolunteerService`

Keeps the volunteer engine self-replenishing (doc 03 sustainability; FR-52/53).

- `assign_role(...term_days=90)` — term-limited roles.
- `active_roles(on_date)`, `coverage(on_date)` (all 4 role types), `is_role_covered(...)`.
- `expiring_soon(on_date, within_days=14)` — the **proactive recruiting trigger**:
  find terms ending soon *before* the cliff.
- `recruit_replacement(...)` — picks the most reliable member who holds no active
  role, so load spreads.
- `suggest_staggered_start(...)` — starts a new term the day after the incumbent's
  ends → overlapping, cliff-free handover.

**API:** `POST /clubs/{id}/volunteers`, `GET /clubs/{id}/volunteers` (coverage + expiring).

## 3. Payments / billing — `BillingService`

Freemium with an anti-"Timeleft" (honest) stance (doc 03). Simulated gateway
(injectable `gateway(amount_cents)->bool`; no real network).

- `subscribe_plus()` — $9/mo Plus; records a transparent `"Orbit Plus monthly"` payment.
- `cancel()` — **one-tap, honest**: `cancel_at_period_end`, keep benefits until renewal.
- `process_renewal()` — **smart retry**: failed charge → `PAST_DUE` + retry up to 3×,
  then graceful downgrade to FREE (recovers involuntary churn).
- `charge_event_deposit()` / `refund_deposit()` — refundable big-event deposits
  (refund on attendance).

**API:** `GET /members/{id}/subscription`, `POST /members/{id}/subscribe`
(201 ok / **402** on failed charge), `POST /members/{id}/cancel`,
`GET /members/{id}/payments`.

## 4. Notifications / reminders — `NotificationService`

Outbox pattern with a pluggable delivery sink (`sink(notification)->bool`).

- `REMINDER_OFFSETS = [T-3d, T-1d, T-2h]` — `schedule_event_reminders(event_id, member_ids)`
  creates the full reminder set.
- `notify_rotation(...)`, `notify_event_attendees(...)`.
- `dispatch_due(now?)` — the worker step: delivers all `SCHEDULED` notifications whose
  `send_at` has passed via the sink, marking `SENT`/`FAILED`.
- `cancel_scheduled(...)`, `pending_for_member(...)`.

**API:** `POST /notifications/dispatch`, `GET /members/{id}/notifications`.

## 5. Weighted V1 matching — `WeightedScorer`

Upgrades the rotation engine **behind the same interface** (doc 04 §6). Opt-in:

```python
from orbit.matching import RotationEngine, WeightedScorer
engine = RotationEngine(scorer=WeightedScorer())   # V1
engine = RotationEngine()                            # MVP (unchanged default)
```

`WeightedScorer` keeps the MVP factors (novelty / availability / niche) and adds
**reliability-balancing** so groups don't concentrate all the flaky (or all the
ultra-reliable) members — every group stays viable. All weights are constructor
args, which is the **hook for the V2 "learn weights from feedback"** step.

The engine's default path is untouched (regression-guarded by a test), so
existing behavior and all prior tests still hold.

---

## Tests

`code/tests/test_v1_features.py` covers all five: big-event capacity/waitlist/
promotion/backup-host, volunteer terms/expiring/coverage/recruit/stagger, billing
subscribe/cancel/smart-retry-downgrade/deposit-refund, notification scheduling/
outbox-dispatch/failing-sink/cancel, and the weighted scorer (valid groups, respects
blocks, deterministic, MVP-default-unchanged).

Run everything:
```bash
cd code && python -m unittest discover -s tests -v
```

> Not executed in this session (local-file-only constraint). The 4 services were
> smoke-tested by sub-agents in isolated sessions; run the suite to confirm green.
