# 09 — File Manifest (What Files the App Needs to Be Built)

*The complete file/folder layout to build Orbit, mapped to the architecture in doc 04. Monorepo structure with three apps (mobile, web, admin), one backend, shared packages, and infrastructure. Stack: React Native (Expo), Next.js, Node/NestJS (or FastAPI), PostgreSQL, Redis, Stripe, AWS.*

---

## 1. Top-level monorepo layout

```
orbit/
├── README.md
├── package.json                 # workspace root (pnpm/yarn workspaces)
├── pnpm-workspace.yaml
├── turbo.json                   # Turborepo pipeline (build/test/lint)
├── .env.example                 # documented env vars (never commit real .env)
├── .gitignore
├── .editorconfig
├── docker-compose.yml           # local Postgres + Redis
├── apps/
│   ├── mobile/                  # React Native (Expo) — members
│   ├── web/                     # Next.js — landing + web member app
│   └── admin/                   # Next.js — club operator console
├── services/
│   └── api/                     # backend (NestJS or FastAPI)
├── packages/
│   ├── shared-types/            # TS types/DTOs shared client+server
│   ├── ui/                      # shared UI components
│   └── config/                  # shared eslint/tsconfig/prettier
├── infra/                       # IaC (CDK or Terraform)
└── docs/                        # these planning docs live here
```

---

## 2. Backend — `services/api/`

```
services/api/
├── package.json
├── tsconfig.json
├── Dockerfile
├── src/
│   ├── main.ts                          # bootstrap
│   ├── app.module.ts
│   ├── config/
│   │   ├── env.ts                        # typed env loading
│   │   └── database.config.ts
│   ├── common/
│   │   ├── guards/                       # auth guards
│   │   ├── interceptors/                 # logging, error mapping
│   │   ├── decorators/
│   │   └── errors/
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── auth.module.ts
│   │   │   ├── auth.controller.ts        # signup, login, OTP verify
│   │   │   ├── auth.service.ts
│   │   │   └── strategies/               # jwt, otp
│   │   ├── members/
│   │   │   ├── members.controller.ts     # profile, preferences, pause
│   │   │   ├── members.service.ts
│   │   │   └── entities/member.entity.ts
│   │   ├── preferences/
│   │   ├── clubs/                        # club config, city launch, density gate
│   │   ├── cycles/                       # cycle lifecycle
│   │   ├── matching/                     # ★ the rotation engine
│   │   │   ├── matching.service.ts       # greedy MVP -> weighted V1
│   │   │   ├── rotation.algorithm.ts     # keep 50% / swap 50%, constraints
│   │   │   ├── constraints.ts            # blocks, women-only, availability
│   │   │   └── scoring.ts                # V1 weighted scoring
│   │   ├── groups/                       # group identity, membership
│   │   ├── events/                       # event lifecycle, ownership, fallback
│   │   │   ├── events.service.ts
│   │   │   ├── ownership.service.ts      # fair owner rotation + decline pass
│   │   │   └── fallback.service.ts       # auto-run partner-venue event
│   │   ├── rsvp/                         # RSVP + commitment mechanic
│   │   ├── reputation/                   # reliability score, streaks
│   │   ├── chat/                         # group messages (or gateway to 3rd party)
│   │   ├── health/                       # group health scoring + at-risk flags
│   │   ├── volunteers/                   # roles, terms, recruiting
│   │   ├── venues/                       # vetted/partner venues
│   │   ├── payments/                     # Stripe subs, event fees, retry, cancel
│   │   ├── notifications/                # push/email/sms dispatch
│   │   └── safety/                       # report/block, moderation
│   ├── workers/
│   │   ├── rotation.cron.ts              # generate cycles on schedule
│   │   ├── reminder.scheduler.ts         # T-3d/T-1d/T-2h reminders
│   │   ├── health.checker.ts             # periodic group health scan
│   │   └── billing.retry.ts              # smart retry on failed payments
│   └── database/
│       ├── migrations/                   # SQL migrations (see doc 07 DDL)
│       ├── seeds/                        # seed data for dev
│       └── data-source.ts                # ORM (TypeORM/Prisma) config
├── test/
│   ├── unit/
│   │   └── rotation.algorithm.spec.ts    # ★ critical: continuity+novelty+constraints
│   ├── integration/
│   │   ├── ownership-fallback.spec.ts    # owner declines -> fallback event
│   │   └── rsvp-reputation.spec.ts
│   └── e2e/
│       └── new-member-first-event.e2e.ts
└── openapi.yaml                          # API contract
```

> If using **FastAPI** instead: swap to `app/main.py`, `app/api/routers/*.py`, `app/services/*.py`, `app/models/*.py` (SQLAlchemy), `alembic/` for migrations, `tests/` with pytest — same module boundaries.

---

## 3. Mobile app — `apps/mobile/` (React Native / Expo)

```
apps/mobile/
├── package.json
├── app.json                     # Expo config
├── App.tsx
├── src/
│   ├── navigation/              # stack/tab navigators
│   ├── screens/
│   │   ├── auth/                # SignUp, VerifyOtp, Login
│   │   ├── onboarding/          # PreferenceQuiz, Welcome
│   │   ├── group/              # MyGroup, GroupChat, GroupIdentity
│   │   ├── events/             # EventDetail, Rsvp, MyEvents
│   │   ├── host/               # HostTurn (tiny-turn), Playbook
│   │   ├── profile/            # Profile, Reliability, Streaks
│   │   └── billing/            # Subscription, ManagePlan (easy cancel)
│   ├── components/             # buttons, cards, avatars
│   ├── api/                    # typed API client (uses shared-types)
│   ├── state/                  # store (Zustand/Redux)
│   ├── hooks/
│   ├── theme/
│   └── utils/
├── assets/                     # icons, images, fonts
└── __tests__/
```

---

## 4. Web + Admin — `apps/web/` and `apps/admin/` (Next.js)

```
apps/web/
├── package.json
├── next.config.js
├── app/                         # App Router
│   ├── page.tsx                 # landing (value prop, waitlist)
│   ├── join/                    # signup / waitlist-to-unlock
│   └── (member)/                # optional web member views
├── components/
├── lib/                         # api client
└── public/

apps/admin/
├── package.json
├── next.config.js
├── app/
│   ├── dashboard/               # KPI overview (sustainability metrics)
│   ├── clubs/                   # config, cadence, city launch + density gate
│   ├── cycles/                  # rotation review (Rotation Steward tools)
│   ├── groups/                  # group health board, at-risk queue
│   ├── volunteers/              # roles, terms, recruiting
│   ├── venues/                  # vetted/partner venue management
│   ├── safety/                  # reports/blocks moderation queue
│   └── billing/                 # revenue, refunds, retries
├── components/
└── lib/
```

---

## 5. Shared packages — `packages/`

```
packages/
├── shared-types/
│   └── src/
│       ├── member.ts  group.ts  cycle.ts  event.ts  rsvp.ts
│       ├── enums.ts                     # matches DB enums (doc 07)
│       └── dto/                         # request/response DTOs
├── ui/
│   └── src/                             # cross-platform-ish shared components
└── config/
    ├── eslint-preset.js
    ├── tsconfig.base.json
    └── prettier.config.js
```

---

## 6. Infrastructure — `infra/`

```
infra/
├── README.md
├── cdk/                          # (or terraform/)
│   ├── bin/app.ts
│   ├── lib/
│   │   ├── network-stack.ts      # VPC, subnets
│   │   ├── database-stack.ts     # RDS Postgres, Redis (ElastiCache)
│   │   ├── api-stack.ts          # ECS/Fargate or Lambda + API Gateway
│   │   ├── storage-stack.ts      # S3 (avatars, photos)
│   │   ├── cdn-stack.ts          # CloudFront for web/admin
│   │   └── monitoring-stack.ts   # alarms on sustainability KPIs
│   └── cdk.json
├── docker/
│   └── api.Dockerfile
└── scripts/
    ├── migrate.sh
    └── seed.sh
```

---

## 7. CI/CD & repo hygiene

```
.github/workflows/
├── ci.yml                        # lint + typecheck + test on PR
├── deploy-api.yml
├── deploy-web.yml
├── deploy-admin.yml
└── mobile-eas-build.yml          # Expo EAS builds

.husky/                           # pre-commit hooks (lint, format)
CODEOWNERS
CONTRIBUTING.md
SECURITY.md
```

---

## 8. Environment variables (`.env.example`)

```
# Core
NODE_ENV=development
API_PORT=4000
DATABASE_URL=postgres://orbit:orbit@localhost:5432/orbit
REDIS_URL=redis://localhost:6379
JWT_SECRET=change-me
JWT_REFRESH_SECRET=change-me

# Payments
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# Notifications
FCM_SERVER_KEY=
APNS_KEY_ID=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
SES_REGION=us-east-1

# Maps
MAPS_API_KEY=

# Storage
S3_BUCKET=orbit-media
AWS_REGION=us-east-1
```

---

## 9. Build priority (which files first)

Map to the phased roadmap (doc 04 §8):

| Phase | Build these files first |
|-------|-------------------------|
| **Phase 0** | none — validate manually (spreadsheet + group chat) |
| **Phase 1 (MVP)** | `services/api` modules: auth, members, preferences, clubs, cycles, **matching**, groups, events (+ownership +fallback), rsvp, reputation, notifications; `workers/rotation.cron`, `reminder.scheduler`; migrations (doc 07); `apps/mobile` auth+onboarding+group+events+host; `apps/admin` cycles+groups; `infra` database+api stacks |
| **Phase 2 (V1)** | payments, health, volunteers, venues, chat, safety; `workers/health.checker`, `billing.retry`; admin dashboard+volunteers+safety+billing; scoring.ts (weighted matching) |
| **Phase 3 (V2)** | multi-city (clubs), learned matching, venue marketplace; monitoring-stack; localization |

---

## 10. The critical file

`services/api/src/modules/matching/rotation.algorithm.ts` is **the heart of the product** — it implements keep-50%/swap-50% partial rotation with the haven't-met anti-clique priority and hard safety constraints (doc 04 §6, doc 07 §5). It must have the most thorough tests (`test/unit/rotation.algorithm.spec.ts`). If any file defines whether Orbit succeeds at its core promise, it's this one.
