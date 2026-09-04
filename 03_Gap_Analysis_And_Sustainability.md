# 03 — Gap Analysis & Sustainability Model (The Added Step)

*This is the step I added because it's the one most club apps skip — and it's what quietly kills them. A club that can't sustain itself financially and operationally dies just as surely as one with no members. This doc defines the market gap Orbit fills and the model that keeps it alive.*

---

## Why this step matters

Doc 01 showed clubs die from structural/social failure. But there's a **second death**: the *business/operational* death. Timeleft's #1 complaint isn't the dinners — it's **billing** ("can't cancel," "unexpected charges," "frequent refund requests"). Meetup groups die when organizers won't pay the fee. Membership orgs lose up to **40% of revenue to involuntary churn** (expired cards, failed renewals). So the "added step" answers: **how does Orbit make money without becoming the thing users complain about, and how does it stay operationally alive?**

---

## Part A — The market gap

Plotting the landscape on two axes exposes an empty quadrant:

- **X-axis:** one-off event ↔ persistent community
- **Y-axis:** organizer-dependent ↔ self-sustaining (no single point of failure)

```
 self-sustaining
        ▲
        │                         ┌─────────────┐
        │                         │   ORBIT     │  ← empty quadrant
        │                         │ (target)    │
        │                         └─────────────┘
        │   Timeleft/222          
        │   (self-run events,     
        │    but no continuity)   
────────┼─────────────────────────────────────────▶
one-off │                         persistent
        │   
        │   (nothing good here)   Meetup / Geneva / Discord
        │                         (persistent BUT organizer-dependent)
        ▼
 organizer-dependent
```

**The gap:** no product is simultaneously **persistent/continuous** *and* **self-sustaining (no single point of failure)**. Event-first apps (Timeleft/222) are self-running but reset every event. Community platforms (Meetup/Geneva) are persistent but die with the organizer. **Orbit targets the empty top-right quadrant.**

### The unmet needs Orbit serves
1. "I want to keep seeing the people I clicked with" — continuity (event-first apps miss this).
2. "I want to keep meeting *new* people too" — controlled novelty (persistent groups miss this).
3. "I don't want it to fall apart when the organizer leaves" — resilience (everything misses this).
4. "I want it to feel fair and easy to pay/leave" — trust (Timeleft fails this).

Orbit is the only design that hits all four via **partial rotation + rotating ownership + transparent model**.

---

## Part B — Monetization model

Principle: **charge for value, never trap the user.** The complaint pattern to avoid at all costs is Timeleft's "can't cancel / surprise charges." Easy cancellation is a *retention* feature because it builds trust.

### Recommended: freemium membership + optional event fees

| Tier | Price (illustrative) | What you get |
|------|----------------------|--------------|
| **Free** | $0 | Join the club, 1 group, biweekly small events, basic profile. Enough to feel real value (the "welcome win"). |
| **Plus** | ~$8–12/mo or ~$79/yr | Priority matching, choose availability/preferences, join multiple groups/niches, monthly big-event priority RSVP, streak perks |
| **Per-event** | at cost + small margin | Big monthly gatherings that have real venue cost (venue, food) — pass-through + small platform fee, shown transparently |

**Why this shape**
- Free tier delivers a genuine welcome win → solves the first-year danger zone and drives word-of-mouth.
- Subscription is the predictable revenue base; event fees cover variable venue costs without inflating the subscription.
- **Transparency**: always show what a charge is for; one-tap cancel; email before every renewal (the anti-Timeleft).

### Revenue streams (layered over time)
1. **Membership subscriptions** (primary, recurring).
2. **Event fees / ticketing** (pass-through + margin for big gatherings).
3. **Venue partnerships** — restaurants/bars pay for guaranteed off-peak group bookings (Timeleft's real B2B engine). High-margin, aligned incentives.
4. **Local sponsorships** for the monthly gathering (a brand sponsors the venue/drinks).
5. **B2B / HR** (later) — companies buy Orbit for employee belonging/onboarding; strong willingness-to-pay, solves loneliness-at-work.

### Billing rules (mandatory — learned from Case 5, doc 02)
- Auto-renew **with** a pre-renewal email + in-app notice.
- **Smart retry** on failed payments (recovers up to ~40% involuntary churn).
- **One-tap cancel**, no dark patterns, no "contact support to cancel."
- Multiple payment methods.
- Clear per-charge descriptions.

---

## Part C — Operational sustainability (the non-financial death)

Money isn't the only sustainability axis. The club must keep *running* even as people come and go.

### 1. The volunteer engine must self-replenish
- Volunteer roles are **term-limited with staggered terms** (no cliff when one leaves).
- App **recruits replacements before terms end** (nudges reliable members).
- Track a **volunteer health score** per club: are enough roles filled? Alert admins when thin.

### 2. Group health monitoring (momentum metrics before renewal risk)
Per doc 01's success pattern, track leading indicators and act *before* churn:
- Attendance rate per group/member; RSVP-to-show ratio.
- "Group at risk" flags: no owner stepped up, turnout < threshold, declining trend.
- Auto-actions: assign a fallback owner, trigger a club-sponsored default event, ping the Health Watcher.

### 3. The auto-run fallback (no dormant groups — kills Case 2)
If no owner accepts a cycle, the app **auto-schedules a default event** at a pre-vetted partner venue at the group's usual slot. A group can *never* go dark just because nobody volunteered.

### 4. Density / liquidity management
Matching quality needs enough members per area. Rules:
- Don't launch a city until a **minimum viable density** (e.g., ~30–50 members in one area).
- Waitlist + "invite friends to unlock your group" to reach density.
- Merge/split groups automatically to hold the 6–8 sweet spot.

### 5. Trust & safety (a silent killer if ignored)
- ID/phone verification, report/block, post-event ratings, code of conduct, women-only / niche group options (learn from Peanut/Les Amis).
- Safety friction is *good* friction — it protects the experience.

---

## Part D — Go-to-market: niche-first, then widen

Learned from Case 7 (shared identity drives belonging) and Peanut (niche focus):

1. **Launch niche + single-city.** Pick one identity (e.g., "new-in-town professionals," "30-something creatives," a neighborhood) in one city. Strong shared identity → strong early belonging → density faster.
2. **Prove the loop:** biweekly small events + one monthly gathering + partial rotation, for ~8–12 weeks, measuring repeat attendance.
3. **Widen** to adjacent niches/neighborhoods once density and retention are proven.
4. **New cities** only after the playbook is repeatable and the venue-partnership motion works.

### The metrics that prove sustainability (not vanity metrics)
| Metric | Why it matters | Target signal |
|--------|----------------|---------------|
| **Repeat attendance rate** | The real product — bonding compounding | Rising over cycles |
| RSVP→show ratio | Commitment mechanic working | > 80% |
| 2nd-event return rate (new members) | First-year danger zone plugged | > 50% |
| Groups with a volunteer owner each cycle | No-single-point-of-failure working | > 90% (rest covered by fallback) |
| Volunteer roles filled | Operational sustainability | 100% critical roles |
| Net member retention (cohort) | Overall health | Flat-to-up per cohort |
| Involuntary churn recovered | Billing hygiene | ~30–40% recovered |

---

## Part E — Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Chicken-and-egg density | Niche-first, single-city, waitlist-to-unlock, minimum-density gate |
| Rotating owners run flat events | Host playbook + vetted venues + tiny-turn design + fallback auto-event |
| Billing backlash (the Timeleft trap) | Transparent charges, easy cancel, pre-renewal notice, smart retry |
| Safety incident | Verification, ratings, reporting, conduct code, niche/women-only options |
| Volunteer supply dries up | Term limits + staggered terms + proactive recruitment + health score |
| Copycat by Timeleft/Meetup | The moat is the *combined* system (rotation + ownership + continuity) + community data, not any single feature |

---

**Bottom line of the added step:** Orbit's defensibility isn't a feature — it's a **self-sustaining system**. It survives member churn (rotation + density mgmt), organizer churn (rotating ownership + fallback), and revenue churn (transparent billing + smart retry + venue partnerships). That trifecta is the empty quadrant no competitor occupies.
