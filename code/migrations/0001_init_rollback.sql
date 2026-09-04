-- Orbit — Migration 0001 rollback.
-- Drops everything created by 0001_init.sql. Destructive: removes all data.
--
-- Apply: psql "$DATABASE_URL" -f code/migrations/0001_init_rollback.sql

BEGIN;

DROP TABLE IF EXISTS notification     CASCADE;
DROP TABLE IF EXISTS payment          CASCADE;
DROP TABLE IF EXISTS subscription     CASCADE;
DROP TABLE IF EXISTS block            CASCADE;
DROP TABLE IF EXISTS meeting_history  CASCADE;
DROP TABLE IF EXISTS volunteer_role   CASCADE;
DROP TABLE IF EXISTS rating           CASCADE;
DROP TABLE IF EXISTS rsvp             CASCADE;
DROP TABLE IF EXISTS event            CASCADE;
DROP TABLE IF EXISTS membership       CASCADE;
DROP TABLE IF EXISTS "group"          CASCADE;
DROP TABLE IF EXISTS venue            CASCADE;
DROP TABLE IF EXISTS cycle            CASCADE;
DROP TABLE IF EXISTS preference       CASCADE;
DROP TABLE IF EXISTS member           CASCADE;
DROP TABLE IF EXISTS club             CASCADE;

DROP TYPE IF EXISTS notification_status;
DROP TYPE IF EXISTS notification_channel;
DROP TYPE IF EXISTS payment_status;
DROP TYPE IF EXISTS subscription_status;
DROP TYPE IF EXISTS subscription_tier;
DROP TYPE IF EXISTS volunteer_type;
DROP TYPE IF EXISTS rsvp_status;
DROP TYPE IF EXISTS event_status;
DROP TYPE IF EXISTS event_type;
DROP TYPE IF EXISTS cycle_status;
DROP TYPE IF EXISTS group_status;
DROP TYPE IF EXISTS member_role;
DROP TYPE IF EXISTS member_status;

COMMIT;
