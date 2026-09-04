# 05 — Requirements (Functional, Non-Functional, Use Cases)

*Requirements for Orbit. IDs: FR = functional, NFR = non-functional, UC = use case. Priority: M = MVP, V1, V2. Each requirement links back to a failure mode (F#, doc 01) or sustainability driver (doc 03).*

---

## Part A — Actors

| Actor | Description |
|-------|-------------|
| **Member** | Signs up, joins a group, RSVPs, attends, chats, builds reputation |
| **Group Owner** | Member whose turn it is to host this cycle's small event (rotates) |
| **Big Event Host** | Volunteer running the monthly gathering |
| **Welcomer** | Volunteer onboarding newcomers |
| **Health Watcher** | Volunteer nudging at-risk groups |
| **Rotation Steward** | Volunteer reviewing/approving each cycle's reshuffle |
| **Club Admin** | Operator: config, safety, billing, city launch |
| **System** | Automated matching, reminders, health checks, billing, fallback events |

---

## Part B — Functional Requirements

### Onboarding & Accounts
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-01 | User can sign up with email/phone and verify identity (OTP) | M | Safety |
| FR-02 | User completes a preference/personality quiz (interests, availability, location, niche, introvert/extrovert) | M | Matching quality |
| FR-03 | On signup, user is placed in a group OR shown a dated countdown to group formation (never a dead end) | M | F8, first-year danger zone |
| FR-04 | System notifies a Welcomer and assigns a first-event buddy to each new member | M | F3, danger zone |
| FR-05 | User can edit profile, preferences, availability, and pause membership | M | Autonomy |

### Groups & Rotation
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-10 | System forms groups of 6–8 members | M | F8 |
| FR-11 | Each cycle, system partially rotates groups (keep ~50%, swap ~50%) | M | F3, F4 (core IP) |
| FR-12 | Matching respects geography, availability, preferences, and "haven't-met" priority | M | Matching quality |
| FR-13 | Matching enforces hard constraints: blocked pairs, women-only/niche | M | Safety |
| FR-14 | Rotation Steward can review and approve/adjust the proposed reshuffle before commit | M | Sanity check |
| FR-15 | Each group has identity: name, avatar, private chat, photo wall, streak | M | Belonging |
| FR-16 | System auto-merges/splits groups to maintain 6–8 size | V1 | F8 |
| FR-17 | Matching uses weighted optimization scoring | V1 | Quality |
| FR-18 | Matching tunes weights from attendance/rating feedback | V2 | Quality |

### Ownership & Events
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-20 | System nominates the next Group Owner via fair rotation (never same person two cycles running) | M | F1 |
| FR-21 | Owner's turn = accept suggested vetted venue + date + confirm (tiny turn) | M | F1 |
| FR-22 | Owner can decline; system auto-passes to next eligible member | M | F1 |
| FR-23 | If no owner accepts, system schedules an auto-run fallback event at a partner venue | M | F1, F2 (no dormant groups) |
| FR-24 | System provides Owner a host playbook (venues, format, invite text) | M | F1 skill floor |
| FR-25 | Biweekly small (group) event lifecycle: create, RSVP, remind, attend, rate | M | Core loop |
| FR-26 | Monthly big gathering lifecycle with Big Event Host + backup co-host | V1 | F1, F8 |
| FR-27 | Event details (venue, time) shared clearly and early (≥ T-3 days) | M | Timeleft fix |
| FR-28 | One-tap RSVP with commitment mechanic applied | M | F5 |
| FR-29 | Post-event: capture attendance, prompt rating, prompt follow-up | M | Bonding compound |

### Reputation & Commitment
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-30 | System tracks reliability score + attendance streak per member | M | F5 |
| FR-31 | Reliable members get waitlist/RSVP priority when events fill | M | F5 |
| FR-32 | Optional refundable deposit for high-cost big gatherings (refund on attend, forfeit on no-show) | V1 | F5 |
| FR-33 | Streaks/milestones unlock badges/perks | V1 | Belonging, recognition |

### Chat & Follow-up
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-40 | Group private chat, persists across partial rotation | M | Continuity |
| FR-41 | Post-event follow-up prompts; "keep in touch" with rotating-out members | V1 | Bonding |

### Health, Volunteers & Safety
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-50 | System computes group-health score (attendance, owner coverage, trend) | M | F2 |
| FR-51 | System flags at-risk groups and notifies Health Watcher; triggers auto-actions | M | F2 |
| FR-52 | Volunteer roles are opt-in, term-limited, with staggered terms | V1 | Sustainability |
| FR-53 | System proactively recruits volunteer replacements before terms end | V1 | Sustainability |
| FR-54 | Members can report/block others; post-event ratings feed safety | M | Safety |
| FR-55 | Support niche/women-only groups | V1 | Safety, niche |

### Payments & Admin
| ID | Requirement | Priority | Addresses |
|----|-------------|----------|-----------|
| FR-60 | Freemium subscription tiers + optional event fees | V1 | Revenue |
| FR-61 | Transparent per-charge descriptions + pre-renewal notice | V1 | Anti-Timeleft |
| FR-62 | One-tap cancel, no dark patterns | V1 | Trust |
| FR-63 | Smart retry on failed payments; multiple payment methods | V1 | Involuntary churn |
| FR-64 | Admin configures club, cadence, cities; city launch gated by min density | M | Density mgmt |
| FR-65 | Admin dashboards for health, volunteers, safety, revenue KPIs | V1 | Sustainability |

---

## Part C — Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-01 | Availability | 99.9% uptime for core APIs |
| NFR-02 | Performance | API p95 < 300ms; app cold start < 3s |
| NFR-03 | Scalability | Support 100k members, 10k concurrent, without redesign |
| NFR-04 | Rotation compute | Cycle generation for a city completes < 5 min; idempotent; re-runnable |
| NFR-05 | Security | Encrypt in transit (TLS) + at rest; hashed credentials; least-privilege |
| NFR-06 | Privacy | GDPR/CCPA: export + delete my data; minimal PII; consent for matching data |
| NFR-07 | Safety | Verification + report/block respond < 24h; audit trail |
| NFR-08 | Reliability | No dormant groups: fallback event guaranteed if owner absent |
| NFR-09 | Observability | Metrics/alerts on sustainability KPIs (doc 03) |
| NFR-10 | Accessibility | WCAG 2.1 AA for web/admin; mobile a11y (screen readers, contrast) |
| NFR-11 | Portability | Cross-platform iOS + Android from launch |
| NFR-12 | Maintainability | Modular services; IaC; automated tests; CI/CD |
| NFR-13 | Localization | i18n-ready (V2 multi-region) |
| NFR-14 | Cost | Async/batch rotation off-peak; autoscale |

---

## Part D — Key Use Cases

### UC-01 — New member joins and gets a good first event
**Actor:** Member (new) · **Pre:** app installed
1. Member signs up, verifies OTP.
2. Completes preference quiz.
3. System places member in a group (or dated countdown).
4. Welcomer notified; first-event buddy assigned.
5. Member RSVPs to first event; gets reminders + clear venue.
6. Member attends; post-event rating + follow-up.
**Post:** member attended a good first event, reliability score started.
**Addresses:** first-year danger zone, F3.

### UC-02 — Cycle rotation runs
**Actor:** System, Rotation Steward
1. Cron triggers cycle generation.
2. System buckets members, keeps ~50% per prior group, fills ~50% new (haven't-met priority), enforces constraints.
3. System assigns next Owner per group (fair rotation).
4. Steward reviews proposal, adjusts, approves.
5. System commits, notifies members of new groups + owner.
**Post:** new groups formed with continuity + novelty; no clique lock-in.
**Addresses:** F3, F4, F1.

### UC-03 — Rotating ownership with fallback
**Actor:** Group Owner, System
1. System nominates next Owner; sends tiny-turn prompt (venue + date suggestion).
2a. Owner confirms → event created.
2b. Owner declines → auto-pass to next.
2c. No one accepts within window → System schedules fallback event at partner venue.
3. Event published with reminders.
**Post:** group meets regardless of volunteer availability.
**Addresses:** F1, F2.

### UC-04 — At-risk group recovery
**Actor:** System, Health Watcher
1. System detects low attendance / no owner / declining trend → flags group.
2. Notifies Health Watcher + triggers auto-action (fallback event, extra reminder).
3. Health Watcher personally nudges quiet members.
**Post:** decline caught before death spiral.
**Addresses:** F2, momentum-before-renewal.

### UC-05 — Member RSVPs with commitment
**Actor:** Member
1. Member views upcoming event.
2. Taps RSVP; commitment mechanic applies (reputation impact / optional deposit).
3. Gets reminders; attends → reliability + streak up (or no-show → down).
**Post:** reliable attendance reinforced.
**Addresses:** F5.

### UC-06 — Subscribe / cancel transparently
**Actor:** Member, Payments
1. Member upgrades to Plus; sees clear price + what's included.
2. Pre-renewal notice before each charge.
3. Member can cancel in one tap anytime; failed payments smart-retried.
**Post:** trust preserved; involuntary churn minimized.
**Addresses:** billing failure modes (doc 03).

### UC-07 — Volunteer term rotation
**Actor:** System, Volunteer, Admin
1. System tracks term end dates (staggered).
2. Before a term ends, system recruits a replacement from reliable members.
3. Handover; outgoing volunteer thanked/recognized.
**Post:** volunteer engine self-replenishes; no cliff.
**Addresses:** volunteer burnout / sustainability.

### UC-08 — Admin launches a new city
**Actor:** Club Admin
1. Admin creates city; sets cadence + niche.
2. Members waitlist until min density reached ("invite to unlock").
3. On density gate met, first cycle runs.
**Post:** city launches only when matching can be good.
**Addresses:** density/liquidity.

---

## Part E — Traceability summary

| Failure mode (doc 01) | Requirements that address it |
|------------------------|------------------------------|
| F1 Organizer burnout | FR-20..24, FR-26, UC-03, UC-07 |
| F2 Attendance decay | FR-23, FR-50, FR-51, NFR-08, UC-04 |
| F3 Cliques | FR-04, FR-11, FR-12, UC-01, UC-02 |
| F4 Staleness | FR-11, FR-17, UC-02 |
| F5 Free-riders | FR-28, FR-30..33, UC-05 |
| F6 Perceived value | belonging FRs (FR-15, FR-33), events, follow-up |
| F7 Logistics/billing friction | FR-27, FR-60..63, UC-06 |
| F8 Scale mismatch | FR-10, FR-16, FR-26, UC-08 |
| Danger zone | FR-03, FR-04, UC-01 |
