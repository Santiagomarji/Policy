# 06 — UML Diagrams

*All diagrams in Mermaid (renders on GitHub, VS Code with Mermaid extension, mermaid.live). Covers: use case, class, sequence (×3), state, activity, and component diagrams. The ER diagram lives in doc 07.*

---

## 1. Use Case Diagram

```mermaid
flowchart LR
    subgraph Actors
        M((Member))
        GO((Group Owner))
        BEH((Big Event Host))
        W((Welcomer))
        HW((Health Watcher))
        RS((Rotation Steward))
        A((Club Admin))
        SYS((System))
    end

    subgraph UseCases
        UC1[Sign up & verify]
        UC2[Complete preference quiz]
        UC3[Join / view group]
        UC4[RSVP to event]
        UC5[Attend & rate event]
        UC6[Group chat & follow-up]
        UC7[Host small event]
        UC8[Run monthly gathering]
        UC9[Welcome newcomers]
        UC10[Nudge at-risk groups]
        UC11[Review rotation]
        UC12[Generate cycle / rotate groups]
        UC13[Assign owner / fallback event]
        UC14[Compute health & flag risk]
        UC15[Manage subscription]
        UC16[Configure club / launch city]
    end

    M --- UC1 & UC2 & UC3 & UC4 & UC5 & UC6 & UC15
    GO --- UC7
    BEH --- UC8
    W --- UC9
    HW --- UC10
    RS --- UC11
    A --- UC16
    SYS --- UC12 & UC13 & UC14
    GO -. is a .- M
    BEH -. is a .- M
```

---

## 2. Class / Domain Model

```mermaid
classDiagram
    class Member {
        +UUID id
        +string name
        +string email
        +string phone
        +bool verified
        +int reliabilityScore
        +int currentStreak
        +MemberStatus status
        +joinClub()
        +updatePreferences()
        +pause()
    }
    class Preference {
        +UUID id
        +string[] interests
        +Availability availability
        +GeoPoint location
        +string niche
        +Personality personality
    }
    class Club {
        +UUID id
        +string name
        +string city
        +Cadence cadence
        +int minDensity
    }
    class Group {
        +UUID id
        +string name
        +string avatarUrl
        +int streak
        +GroupStatus status
    }
    class Cycle {
        +UUID id
        +date startDate
        +date endDate
        +CycleStatus status
        +generate()
        +commit()
    }
    class Membership {
        +UUID id
        +Role role
        +date joinedAt
        +bool isOwnerThisCycle
    }
    class Event {
        +UUID id
        +EventType type
        +datetime startsAt
        +Venue venue
        +EventStatus status
        +bool isFallback
        +publish()
        +cancel()
    }
    class RSVP {
        +UUID id
        +RsvpStatus status
        +bool attended
        +Money deposit
    }
    class Venue {
        +UUID id
        +string name
        +GeoPoint location
        +bool vetted
        +bool partner
    }
    class VolunteerRole {
        +UUID id
        +RoleType type
        +date termStart
        +date termEnd
    }
    class Rating {
        +UUID id
        +int score
        +string comment
    }
    class Subscription {
        +UUID id
        +Tier tier
        +SubStatus status
        +date renewsAt
    }
    class Report {
        +UUID id
        +string reason
        +ReportStatus status
    }

    Club "1" --> "*" Member : has
    Club "1" --> "*" Cycle : runs
    Club "1" --> "*" Group : contains
    Member "1" --> "1" Preference : has
    Member "1" --> "*" Membership : holds
    Group "1" --> "*" Membership : includes
    Cycle "1" --> "*" Group : forms
    Group "1" --> "*" Event : schedules
    Event "1" --> "*" RSVP : receives
    Member "1" --> "*" RSVP : makes
    Event "1" --> "1" Venue : at
    Event "1" --> "*" Rating : gets
    Member "1" --> "*" VolunteerRole : serves
    Member "1" --> "0..1" Subscription : pays
    Member "1" --> "*" Report : files
```

---

## 3. Sequence — Cycle rotation (UC-02)

```mermaid
sequenceDiagram
    participant Cron
    participant Rotation as RotationService
    participant DB
    participant Steward as RotationSteward
    participant Notif as NotificationService
    participant M as Members

    Cron->>Rotation: triggerCycleGeneration(clubId)
    Rotation->>DB: load members, prior groups, history, constraints
    Rotation->>Rotation: bucket by area+availability
    loop each prior group
        Rotation->>Rotation: keep ~50% (reliability + mutual keep)
    end
    Rotation->>Rotation: fill ~50% new (haven't-met priority, prefs, geo)
    Rotation->>Rotation: enforce hard constraints (blocks, women-only)
    Rotation->>Rotation: assign next Owner (fair rotation)
    Rotation->>Steward: submit proposal for review
    Steward-->>Rotation: approve / adjust
    Rotation->>DB: commit new groups + owners
    Rotation->>Notif: notify members of new group + owner
    Notif->>M: push/email "your new group for this cycle"
```

---

## 4. Sequence — Rotating ownership with fallback (UC-03)

```mermaid
sequenceDiagram
    participant SYS as System
    participant Owner as NominatedOwner
    participant Event as EventService
    participant Venue as VenueService
    participant Notif

    SYS->>Owner: tiny-turn prompt (suggested venue + date)
    alt Owner confirms
        Owner->>Event: confirm venue + date
        Event->>Venue: reserve vetted venue
        Event->>Notif: publish event + reminders
    else Owner declines
        Owner-->>SYS: decline
        SYS->>SYS: pass to next eligible member
    else No response within window
        SYS->>Venue: pick partner fallback venue
        SYS->>Event: create fallback event (isFallback=true)
        Event->>Notif: publish fallback event
    end
    Note over Event,Notif: Group meets regardless of volunteer availability
```

---

## 5. Sequence — Member first event (UC-01)

```mermaid
sequenceDiagram
    participant U as NewMember
    participant Auth
    participant Match as MatchingService
    participant W as Welcomer
    participant Notif
    participant Event

    U->>Auth: sign up + OTP verify
    U->>Match: submit preference quiz
    Match->>Match: place in group or schedule countdown
    Match->>W: notify Welcomer + assign buddy
    W->>U: personal welcome message
    Event->>U: upcoming first event + clear venue (>=T-3d)
    U->>Event: RSVP
    Event->>U: reminders (T-3d, T-1d, T-2h)
    U->>Event: attend
    Event->>U: rating + follow-up prompt
```

---

## 6. State — Event lifecycle

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Published : owner confirms / fallback created
    Published --> Full : capacity reached
    Full --> Published : spot opens
    Published --> Cancelled : owner cancels / too few RSVPs
    Published --> InProgress : start time
    Full --> InProgress : start time
    InProgress --> Completed : ends
    Completed --> [*]
    Cancelled --> [*]
```

---

## 7. State — Group health

```mermaid
stateDiagram-v2
    [*] --> Forming
    Forming --> Healthy : first event held, attendance ok
    Healthy --> AtRisk : attendance < threshold OR no owner OR declining
    AtRisk --> Healthy : recovery (fallback event + nudges work)
    AtRisk --> Dissolving : sustained failure
    Dissolving --> Merged : members merged into other groups
    Merged --> [*]
    Healthy --> Rotating : cycle end
    Rotating --> Healthy : new cycle committed
```

---

## 8. Activity — Cycle + ownership + fallback (end to end)

```mermaid
flowchart TD
    A[Cycle timer fires] --> B[Generate group proposal<br/>keep 50% / swap 50%]
    B --> C{Steward approves?}
    C -- adjust --> B
    C -- yes --> D[Commit groups + notify]
    D --> E[Nominate Group Owner]
    E --> F{Owner confirms?}
    F -- yes --> G[Create event at chosen venue]
    F -- declines --> H{More eligible members?}
    H -- yes --> E
    H -- no --> I[Create fallback event<br/>at partner venue]
    G --> J[Send reminders]
    I --> J
    J --> K[Event happens]
    K --> L[Capture attendance + ratings]
    L --> M[Update reliability, streaks, health]
    M --> A
```

---

## 9. Component / Deployment

```mermaid
flowchart TB
    subgraph Clients
        MA[Mobile App - React Native]
        WA[Web / Landing - Next.js]
        AC[Admin Console - Next.js]
    end
    GW[API Gateway<br/>auth, routing]
    subgraph Services
        AUTH[Auth]
        USR[Users]
        MATCH[Matching/Rotation]
        GRP[Groups]
        EVT[Events/RSVP]
        CHAT[Chat]
        PAY[Payments]
        NOT[Notifications]
        HV[Health/Volunteers]
        ADM[Admin]
    end
    subgraph Data
        PG[(PostgreSQL)]
        RD[(Redis)]
        S3[(S3 storage)]
    end
    subgraph Workers
        CRON[Rotation cron]
        REM[Reminder scheduler]
        HLTH[Health checks]
        RETRY[Billing retry]
    end
    subgraph External
        STRIPE[Stripe]
        PUSH[FCM/APNs]
        COMM[SES/Twilio]
        MAPS[Maps/Places]
    end

    MA & WA & AC --> GW --> AUTH & USR & MATCH & GRP & EVT & CHAT & PAY & NOT & HV & ADM
    Services --> PG
    Services --> RD
    GRP & EVT --> S3
    MATCH --> CRON
    NOT --> REM
    HV --> HLTH
    PAY --> RETRY
    PAY --> STRIPE
    NOT --> PUSH & COMM
    EVT --> MAPS
```
