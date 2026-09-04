-- Orbit — Rotating Social Club
-- Migration 0001: initial production schema (PostgreSQL).
--
-- This is the durable, scalable store that replaces the local JSON file
-- (orbit.services.json_repository) when you outgrow single-file persistence.
-- It is provider-agnostic standard PostgreSQL — runs on any Postgres 13+,
-- self-hosted or managed, with no vendor-specific extensions required
-- (PostGIS is optional and only needed for true geo-radius matching).
--
-- Apply:   psql "$DATABASE_URL" -f code/migrations/0001_init.sql
-- Rollback: see 0001_init_rollback.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- Enum types (mirror orbit/domain/enums.py)
-- ---------------------------------------------------------------------------
CREATE TYPE member_status  AS ENUM ('pending','active','paused','banned');
CREATE TYPE member_role    AS ENUM ('member','owner');
CREATE TYPE group_status   AS ENUM ('forming','healthy','at_risk','dissolving','merged','rotating');
CREATE TYPE cycle_status   AS ENUM ('planned','proposed','committed','closed');
CREATE TYPE event_type     AS ENUM ('small','big');
CREATE TYPE event_status   AS ENUM ('draft','published','full','in_progress','completed','cancelled');
CREATE TYPE rsvp_status    AS ENUM ('going','waitlist','declined','no_show');
CREATE TYPE volunteer_type AS ENUM ('big_event_host','welcomer','health_watcher','rotation_steward');

-- ---------------------------------------------------------------------------
-- Core tables
-- ---------------------------------------------------------------------------
CREATE TABLE club (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    city         text NOT NULL,
    cadence      text NOT NULL DEFAULT 'biweekly+monthly',
    min_density  int  NOT NULL DEFAULT 30,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE member (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id           uuid NOT NULL REFERENCES club(id) ON DELETE CASCADE,
    name              text NOT NULL,
    email             text NOT NULL,
    phone             text NOT NULL DEFAULT '',
    verified          boolean NOT NULL DEFAULT false,
    reliability_score int NOT NULL DEFAULT 100 CHECK (reliability_score BETWEEN 0 AND 100),
    current_streak    int NOT NULL DEFAULT 0 CHECK (current_streak >= 0),
    status            member_status NOT NULL DEFAULT 'active',
    member_token      text NOT NULL DEFAULT gen_random_uuid()::text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (club_id, email)
);

-- Member matching preferences (1:1 with member).
CREATE TABLE preference (
    member_id    uuid PRIMARY KEY REFERENCES member(id) ON DELETE CASCADE,
    interests    jsonb NOT NULL DEFAULT '[]',
    availability jsonb NOT NULL DEFAULT '[]',   -- list of day tokens
    lat          double precision,
    lng          double precision,
    niche        text,
    personality  jsonb NOT NULL DEFAULT '[]'
);

CREATE TABLE cycle (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id    uuid NOT NULL REFERENCES club(id) ON DELETE CASCADE,
    start_date date NOT NULL,
    end_date   date NOT NULL,
    status     cycle_status NOT NULL DEFAULT 'planned',
    CHECK (end_date >= start_date)
);

CREATE TABLE venue (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id  uuid NOT NULL REFERENCES club(id) ON DELETE CASCADE,
    name     text NOT NULL,
    lat      double precision,
    lng      double precision,
    vetted   boolean NOT NULL DEFAULT false,
    partner  boolean NOT NULL DEFAULT false
);

CREATE TABLE "group" (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id    uuid NOT NULL REFERENCES club(id) ON DELETE CASCADE,
    cycle_id   uuid NOT NULL REFERENCES cycle(id) ON DELETE CASCADE,
    name       text NOT NULL,
    owner_id   uuid REFERENCES member(id) ON DELETE SET NULL,
    streak     int NOT NULL DEFAULT 0,
    status     group_status NOT NULL DEFAULT 'forming'
);

-- Join row: which members are in which group for a cycle.
CREATE TABLE membership (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id           uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    group_id            uuid NOT NULL REFERENCES "group"(id) ON DELETE CASCADE,
    role                member_role NOT NULL DEFAULT 'member',
    is_owner_this_cycle boolean NOT NULL DEFAULT false,
    joined_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (member_id, group_id)
);

CREATE TABLE event (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id    uuid NOT NULL REFERENCES "group"(id) ON DELETE CASCADE,
    venue_id    uuid REFERENCES venue(id) ON DELETE SET NULL,
    owner_id    uuid REFERENCES member(id) ON DELETE SET NULL,  -- NULL for fallback events
    type        event_type NOT NULL DEFAULT 'small',
    starts_at   timestamptz NOT NULL,
    status      event_status NOT NULL DEFAULT 'draft',
    is_fallback boolean NOT NULL DEFAULT false
);

CREATE TABLE rsvp (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id      uuid NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    member_id     uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    status        rsvp_status NOT NULL DEFAULT 'going',
    attended      boolean NOT NULL DEFAULT false,
    deposit_cents int NOT NULL DEFAULT 0,
    UNIQUE (event_id, member_id)
);

CREATE TABLE rating (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id  uuid NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    member_id uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    score     int NOT NULL CHECK (score BETWEEN 1 AND 5),
    comment   text
);

CREATE TABLE volunteer_role (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id  uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    club_id    uuid NOT NULL REFERENCES club(id) ON DELETE CASCADE,
    type       volunteer_type NOT NULL,
    term_start date NOT NULL,
    term_end   date NOT NULL,
    CHECK (term_end >= term_start)
);

-- Anti-clique engine input: who has met whom (directional rows, inserted both ways).
CREATE TABLE meeting_history (
    member_id       uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    other_member_id uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    cycle_id        uuid REFERENCES cycle(id) ON DELETE SET NULL,
    met_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, other_member_id)
);

-- Safety hard constraint: blocked pairs (store both directions for symmetry).
CREATE TABLE block (
    member_id  uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    blocked_id uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    PRIMARY KEY (member_id, blocked_id)
);

-- ---------------------------------------------------------------------------
-- V1 feature tables (big events reuse `event`; these add billing/notifs)
-- ---------------------------------------------------------------------------
CREATE TYPE subscription_tier   AS ENUM ('free','plus');
CREATE TYPE subscription_status AS ENUM ('active','past_due','cancelled');
CREATE TYPE payment_status      AS ENUM ('succeeded','failed','refunded','pending');
CREATE TYPE notification_channel AS ENUM ('push','email','sms');
CREATE TYPE notification_status AS ENUM ('scheduled','sent','failed','cancelled');

CREATE TABLE subscription (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id            uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    tier                 subscription_tier NOT NULL DEFAULT 'free',
    status               subscription_status NOT NULL DEFAULT 'active',
    price_cents          int NOT NULL DEFAULT 0,
    renews_at            timestamptz,
    cancel_at_period_end boolean NOT NULL DEFAULT false,
    retry_count          int NOT NULL DEFAULT 0,
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (member_id)
);

CREATE TABLE payment (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id       uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    amount_cents    int NOT NULL,
    description     text NOT NULL DEFAULT '',
    status          payment_status NOT NULL DEFAULT 'pending',
    subscription_id uuid REFERENCES subscription(id) ON DELETE SET NULL,
    event_id        uuid REFERENCES event(id) ON DELETE SET NULL,
    refunded_cents  int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notification (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id  uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    kind       text NOT NULL,
    body       text NOT NULL DEFAULT '',
    send_at    timestamptz NOT NULL,
    channel    notification_channel NOT NULL DEFAULT 'push',
    status     notification_status NOT NULL DEFAULT 'scheduled',
    event_id   uuid REFERENCES event(id) ON DELETE SET NULL,
    sent_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Big events reuse the `event` table; add the columns they need.
ALTER TABLE event ADD COLUMN IF NOT EXISTS backup_owner_id uuid REFERENCES member(id) ON DELETE SET NULL;
ALTER TABLE event ADD COLUMN IF NOT EXISTS club_id uuid REFERENCES club(id) ON DELETE CASCADE;
ALTER TABLE event ADD COLUMN IF NOT EXISTS capacity int;
-- big events are club-scoped; allow group_id to be empty/nullable for them.
ALTER TABLE event ALTER COLUMN group_id DROP NOT NULL;

-- ---------------------------------------------------------------------------
-- Indexes for the hot query paths (see docs/07_Database_Design.md sec.5)
-- ---------------------------------------------------------------------------
CREATE INDEX idx_member_club        ON member(club_id);
CREATE INDEX idx_member_status      ON member(status);
CREATE INDEX idx_cycle_club         ON cycle(club_id);
CREATE INDEX idx_group_cycle        ON "group"(cycle_id);
CREATE INDEX idx_membership_group   ON membership(group_id);
CREATE INDEX idx_membership_member  ON membership(member_id);
CREATE INDEX idx_event_group        ON event(group_id);
CREATE INDEX idx_event_starts       ON event(starts_at);
CREATE INDEX idx_rsvp_event         ON rsvp(event_id);
CREATE INDEX idx_rsvp_member        ON rsvp(member_id);
CREATE INDEX idx_meeting_member     ON meeting_history(member_id);
CREATE INDEX idx_venue_club_partner ON venue(club_id, partner);
CREATE INDEX idx_pref_geo           ON preference(lat, lng);
CREATE INDEX idx_volrole_club       ON volunteer_role(club_id);
CREATE INDEX idx_subscription_member ON subscription(member_id);
CREATE INDEX idx_payment_member     ON payment(member_id);
CREATE INDEX idx_notification_member ON notification(member_id);
CREATE INDEX idx_notification_due   ON notification(status, send_at);
CREATE INDEX idx_event_club         ON event(club_id);

COMMIT;

-- ---------------------------------------------------------------------------
-- Notes
-- ---------------------------------------------------------------------------
-- * gen_random_uuid() is built into PostgreSQL 13+ (pgcrypto is bundled).
-- * For true distance matching, enable PostGIS and add geography(Point)
--   columns on preference and venue; the app's area-bucketing works without it.
-- * The Python JsonFileRepository and this schema are interchangeable behind
--   the same repository method names, so services need no changes to switch.
