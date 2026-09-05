# 04 — Orbit App Plan (Product + Technical)

*The full plan: what we're building, how it works, how it's architected, and the phased roadmap. Every feature traces to a failure mode (doc 01), a competitor gap (doc 02), or the sustainability model (doc 03).*

---

## 1. Product vision

**Orbit is a social club that can't die.** Members join, get placed in a small group (6–8), meet biweekly for small events and monthly for a big club gathering. Groups **partially rotate** each cycle so you keep your bonds *and* keep meeting new people. **Group ownership rotates** and a **club volunteer pool** runs the bigger machine — so there's no single organizer to burn out. The app automates all logistics so any member's "turn" to host is tiny and stress-free.

**One-liner:** *The only club app where the meeting is the product, groups bond over time, and nothing breaks when one person quits.*

---

## 2. How the case-study lessons are built in

*(Per the research + real-world clubs in docs 01–02, threaded directly into features.)*

| Lesson (source) | Built into Orbit as |
|-----------------|---------------------|
| Great event ≠ friendship (Timeleft) | **Persistent-but-rotating groups** + **post-event follow-up** so bonds compound |
| Organizer burnout kills groups (Meetup graveyard) | **Rotating ownership** + **volunteer pool** + **auto-run fallback event** |
| Match ≠ meeting (Bumble BFF dead chats) | **Event-first**: RSVP to a real event is the core loop, not messaging |
| Un-welcomed newcomers leave (camera clubs) | **Welcomer role** + **guaranteed good first event** + first-event buddy |
| Involuntary billing churn (associations) | **Transparent billing, easy cancel, smart retry** |
| Fixed rhythm builds habit (every-Wednesday) | **Stable cadence**: biweekly group night + first-Saturday monthly gathering |
| Shared identity drives belonging (run clubs) | **Group names/identity, club rituals, streaks, niche-first launch** |
| Cliques calcify | **Partial rotation algorithm** keeps circles open |

---

## 3. Roles & operating model

```
CLUB
 ├── Members ──────────────► RSVP, attend, chat, build streaks
 ├── Group Owner (rotates)─► hosts this cycle's small event (tiny turn, playbook)
 └── Club Volunteers (pool, term-limited, staggered)
        ├── Big Event Host ─► runs monthly gathering (+ backup co-host)
        ├── Welcomer ───────► onboards newcomers, guarantees good first event
        ├── Health Watcher ─► nudges at-risk groups the app flags
        └── Rotation Steward► sanity-checks the auto-reshuffle each cycle
   Admin (club operator) ──► config, safety, billing, city launch
```

**Design rule:** the app does logistics (assignment, reminders, RSVP, venue), humans do the human parts (welcoming, noticing, judgment). See doc 01 principle #1: *no single point of failure.*

---

## 4. Core features

### 4.1 Onboarding (plugs the first-year danger zone)
- Sign up + verify (phone/ID).
- Personality/preference quiz (interests, availability, location, introvert/extrovert, niche) → feeds matching.
- Immediate placement into a group OR a clear "your group forms on {date}" with a countdown (no dead-end).
- **Welcomer** auto-notified; new member flagged for a first-event buddy.

### 4.2 The rotation engine (core IP — see §6)
- Each cycle, groups **partially reshuffle** (keep ~50%, swap ~50%).
- Respects: geography, availability, preferences, "haven't-met" priority, safety constraints.
- **Rotation Steward** reviews the proposed reshuffle before it's committed.

### 4.3 Rotating ownership
- App nominates next owner (fair rotation, never same person twice running).
- Owner's turn = accept a **suggested vetted venue + date** + tap confirm (tiny turn).
- Owner can decline → auto-passes to next.
- No one accepts → **auto-run fallback event** at a partner venue (group never goes dark).

### 4.4 Events & RSVP
- Biweekly small event (group) + monthly big gathering (club).
- One-tap RSVP with **commitment mechanic** (see §5).
- Auto-reminders (T-3d, T-1d, T-2h); early, clear venue details (fixes Timeleft's "late location" gripe).
- Post-event: attendance capture + rating + **follow-up prompt** ("liked meeting Sam? they're in your group next cycle too").

### 4.5 Group & club identity (belonging by design)
- Each group gets a name, avatar, private chat, shared photo wall, streak counter.
- Club-level rituals: monthly-gathering traditions, milestone badges, member spotlights.

### 4.6 Chat & follow-up
- Group chat (persists across partial rotation for continuity).
- Post-event follow-up, "keep in touch" with people rotating out.

### 4.7 Commitment / reputation
- Streaks, reliability score, waitlist priority for reliable members; optional deposit (see §5).

### 4.8 Health & volunteer ops
- Group-health dashboard (attendance, owner coverage, trend).
- At-risk flags + auto-actions + Health Watcher nudges.
- Volunteer term tracking + proactive replacement recruiting.

### 4.9 Safety & trust
- Verification, report/block, post-event ratings, conduct code, niche/women-only groups.

### 4.10 Admin & billing
- Club config, city launch gating (min density), transparent subscription/event fees, smart-retry, one-tap cancel.

---

## 5. The commitment mechanic (recommended default)

To avoid the Timeleft billing backlash while still killing flaking, default to a **non-monetary-first, layered** approach:

1. **Reputation + streaks** (primary): reliable attendance builds a visible score + streak; unlocks perks and priority.
2. **Waitlist priority** (social): reliable members get first pick when events fill; flakers drift down.
3. **Optional refundable deposit** (only for high-cost big gatherings): fully refunded on attendance, forfeited on no-show; always transparent.

> Confirm during build which layer(s) to ship first. Reputation+streak is lowest-friction and recommended for MVP.

---

## 6. The rotation algorithm (core IP)

**Goal:** every cycle, form groups of 6–8 that (a) keep ~half the prior group together for continuity, (b) introduce ~half new people for novelty/anti-clique, (c) respect geography/availability/preferences/safety.

**Inputs:** members (location, availability, prefs, niche), prior group history (who's met whom), reliability score, owner-history, safety constraints (blocks, women-only).

**Approach (phased):**
- **MVP — greedy + constraints:** bucket by area+availability; within each bucket, form groups keeping ~50% of prior group, filling the rest with members who *haven't met* recent members, balancing size 6–8. Deterministic, explainable, Steward-reviewable.
- **V1 — weighted optimization:** score candidate groupings on continuity, novelty, compatibility, reliability balance, size; pick top; expose scores to Steward.
- **V2 — learned matching:** use attendance/rating feedback to tune weights per city/niche.

**Pseudocode (MVP):**
```
for each area_availability_bucket:
    members = eligible_members(bucket)          # active, not paused
    prior_groups = last_cycle_groups(bucket)
    new_groups = []
    for pg in prior_groups:
        keep = pick ~50% of pg (highest reliability + mutual "want to keep")
        seed a new_group with keep
    pool = members not yet placed
    for ng in new_groups:
        fill ng to size 6-8 from pool, preferring:
            - members who have NOT met ng's current members (anti-clique)
            - compatible prefs/niche
            - geographic proximity
    balance leftover pool into new or merged groups (hold 6-8)
    assign next Owner per group (fair rotation)
    emit proposal -> Rotation Steward review -> commit
```

**Safety/constraint hard rules:** never group blocked pairs; honor women-only/niche; never assign owner two cycles running; respect availability.

---

## 7. System architecture

### 7.1 High-level (cross-platform mobile-first + web admin)

```
┌──────────────┐   ┌──────────────┐   ┌───────────────┐
│ Mobile app   │   │ Web app /    │   │ Admin console │
│ (iOS+Android)│   │ landing      │   │ (club ops)    │
│ React Native │   │ Next.js      │   │ Next.js       │
└──────┬───────┘   └──────┬───────┘   └──────┬────────┘
       └──────────────────┼──────────────────┘
                          ▼
                 ┌──────────────────┐
                 │  API Gateway      │  REST/GraphQL, auth
                 └────────┬──────────┘
                          ▼
        ┌───────────────────────────────────────┐
        │           Backend services             │
        │  Auth │ Users │ Matching/Rotation │     │
        │  Groups │ Events/RSVP │ Chat │ Payments │
        │  Notifications │ Health/Volunteers │     │
        └───────┬───────────────┬────────────────┘
                ▼               ▼
        ┌────────────┐   ┌──────────────┐
        │ PostgreSQL │   │ Redis (cache/ │
        │ (core data)│   │ queues/locks) │
        └────────────┘   └──────────────┘
                ▼
   ┌───────────────────────────────────────────┐
   │ Async workers: rotation cron, reminders,    │
   │ health checks, billing retries              │
   └───────────────────────────────────────────┘
   External: Push (FCM/APNs) │ Email/SMS (SES/Twilio) │
             Payments (Stripe) │ Maps/Places │ Storage (S3)
```

### 7.2 Recommended stack (pragmatic, hireable, scalable)
- **Mobile:** React Native (Expo) — one codebase, iOS+Android (fixes 222's iOS-only gap).
- **Web/admin:** Next.js + React.
- **Backend:** Node.js (NestJS) or Python (FastAPI) — REST + GraphQL.
- **DB:** PostgreSQL (relational fits groups/cycles/RSVPs); Redis for cache/queues/locks.
- **Async:** cron + queue (BullMQ / Celery / SQS) for rotation, reminders, health, billing retry.
- **Auth:** JWT + refresh; phone/OTP; optional OAuth.
- **Payments:** Stripe (subscriptions + smart retry + easy cancel out of the box).
- **Notifications:** FCM/APNs push; SES/Twilio email+SMS.
- **Infra:** AWS (ECS/Fargate or Lambda), RDS Postgres, S3, CloudFront; IaC via CDK/Terraform.
- **Observability:** structured logs, metrics, alerts on the sustainability KPIs (doc 03).

### 7.3 Key services
| Service | Responsibility |
|---------|----------------|
| Auth | signup, login, verification, sessions |
| Users | profiles, preferences, reliability score |
| Matching/Rotation | the algorithm, cycle generation, steward review |
| Groups | membership, identity, chat metadata |
| Events/RSVP | event lifecycle, RSVP, attendance, commitment mechanic |
| Chat | group messaging, follow-up |
| Payments | subscriptions, event fees, retry, cancel |
| Notifications | push/email/SMS, reminder scheduling |
| Health/Volunteers | health scores, at-risk flags, volunteer terms, recruiting |
| Admin | club config, city gating, safety, reporting |

---

## 8. Phased roadmap

### Phase 0 — Validate (no/low code, ~2–4 wks)
Run one niche group in one city **manually** (spreadsheet + group chat). Prove the loop: biweekly + monthly + partial rotation + rotating host. Learn the real friction before building.

### Phase 1 — MVP (~8–12 wks)
Single city, single niche. Ship:
- Signup + verify + preference quiz
- Greedy rotation algorithm + Steward review
- Groups + group chat + identity
- Biweekly event + RSVP + reminders + attendance
- Rotating ownership + host playbook + auto-run fallback
- Welcomer flow
- Basic reliability/streak (non-monetary commitment)
- Admin console (config, safety, health basics)
**Goal:** prove repeat-attendance and no-dormant-groups.

### Phase 2 — V1 (~3–4 mo)
- Monthly big gathering + Big Event Host role + backup
- Payments (freemium + event fees, transparent billing, smart retry, easy cancel)
- Weighted optimization matching
- Full health dashboard + volunteer term management + proactive recruiting
- Follow-up features, badges/milestones
- Multi-group / multi-niche in one city
**Goal:** prove sustainability KPIs (doc 03) + monetization.

### Phase 3 — V2 (scale)
- Multi-city with density gating
- Learned matching (feedback-tuned)
- Venue-partnership marketplace + sponsorships
- B2B/HR offering
- Advanced safety/trust, localization
**Goal:** repeatable city playbook + defensible network.

---

## 9. Success criteria (tie to sustainability metrics)
- Repeat attendance rate rising over cycles
- RSVP→show > 80%; new-member 2nd-event return > 50%
- Groups with owner-or-fallback each cycle > 99% (no dormant groups)
- Critical volunteer roles 100% filled
- Cohort retention flat-to-up
(Full metric definitions in doc 03, Part D.)

---

*Requirements detail → doc 05. Diagrams → doc 06. Database → doc 07. Live comparison → doc 08. File manifest → doc 09.*
