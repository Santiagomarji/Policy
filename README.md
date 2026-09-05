# Orbit — Rotating Social Club App

**A social club that is engineered to *not die*.**

People sign up, get assigned to a small **rotating group**, meet **biweekly** for small events, and gather **monthly** for a big event. The whole thing runs on **rotating group ownership + club volunteers** — so there is no single organizer to burn out and no single point of failure.

> Working name: **Orbit** (members move in orbits — small orbits meet often, the whole system gathers monthly).

---

## The core idea in one paragraph

Most social clubs die for predictable structural reasons — the organizer burns out, attendance decays into an empty-room death spiral, cliques wall off newcomers, the format goes stale, and free-riders flake because there is no skin in the game. Orbit is designed as a direct structural counter to each of these. **Rotating small groups** kill cliques and staleness. **Rotating ownership + a volunteer pool** kill organizer burnout. **A two-tier event rhythm** (intimate biweekly + energetic monthly) solves the scale mismatch. **Commitment mechanics** and **automated logistics** kill flaking and friction. Belonging is designed in through group identity, streaks, and rituals — not left to chance.

---

## Document index

Read in this order:

| # | Document | What's inside |
|---|----------|---------------|
| 1 | [`01_Research_Why_Clubs_Fail_And_Succeed.md`](01_Research_Why_Clubs_Fail_And_Succeed.md) | The research: 8 failure modes, the success patterns, and the design principles that fall out of them |
| 2 | [`02_Competitor_Analysis.md`](02_Competitor_Analysis.md) | Timeleft, Meetup, Bumble BFF, 222, Peanut and others — strengths, weaknesses, what to improve |
| 3 | [`03_Gap_Analysis_And_Sustainability.md`](03_Gap_Analysis_And_Sustainability.md) | **The added step** — the market gap Orbit fills + the monetization/sustainability model that keeps it alive |
| 4 | [`04_App_Plan.md`](04_App_Plan.md) | Full product + technical plan: architecture, features, roles, the rotation algorithm, phased roadmap |
| 5 | [`05_Requirements.md`](05_Requirements.md) | Functional + non-functional requirements + use cases |
| 6 | [`06_UML_Diagrams.md`](06_UML_Diagrams.md) | Use case, class, sequence, state, and ER diagrams (Mermaid) |
| 7 | [`07_Database_Design.md`](07_Database_Design.md) | Schema, entities, relationships, indexes, key queries |
| 8 | [`08_Live_App_Comparison.md`](08_Live_App_Comparison.md) | Feature matrix: Orbit vs. the live apps |
| 9 | [`09_File_Manifest.md`](09_File_Manifest.md) | Every file/folder the app needs to be built (frontend, backend, infra) |
| 10 | [`10_Deployment_And_Hosting.md`](10_Deployment_And_Hosting.md) | 3 ways to host Orbit (all outside Amazon) + web UI + auth + SQL wiring |
| 11 | [`11_Customer_Journeys.md`](11_Customer_Journeys.md) | Customer-experience audit: member/operator journeys, friction found & fixed, test inventory |
| 12 | [`12_V1_Features.md`](12_V1_Features.md) | The 5 V1 features built: big gatherings, volunteer terms, billing, notifications, weighted matching |
| 13 | [`13_Hardening_Pass.md`](13_Hardening_Pass.md) | SQL deep-review + Welcomer onboarding + Ratings/follow-up + per-member auth |

> A working, runnable implementation lives in [`code/`](code/README.md) — pure-Python core (rotation engine, services), JSON + PostgreSQL storage, stdlib REST API, single-file web UI, CLI, and a full test suite.

---

## The design decisions locked so far

| Decision | Choice | Why |
|----------|--------|-----|
| What rotates | **Group membership + group ownership both rotate** | Rotation is the anti-clique / anti-staleness engine |
| Membership rotation | **Partial (keep ~half, swap ~half) each cycle** | Balances real bonds with constant novelty |
| Operating model | **Rotating group ownership + club volunteer pool** | Removes the single-organizer point of failure |
| Event rhythm | **Biweekly small (group) + monthly big (club)** | Two tiers: intimacy + energy |
| Anti-flaking | **Commitment mechanic** (deposit / streak / waitlist priority) | Reliability is the product |

## Open decisions (to confirm before build)

- **Commitment mechanic**: paid deposit vs. reputation/streak vs. waitlist priority (or a mix). See doc 03/04.
- **Platform**: mobile (iOS/Android) vs. web vs. both. Plan assumes **cross-platform mobile first + a light web admin**.
- **Launch scale**: single city first (recommended) vs. multi-city.

---

*Generated as a planning deliverable set. All competitor facts are cited from public sources in doc 02; treat market claims as of 2025–2026 and re-verify before investing.*
