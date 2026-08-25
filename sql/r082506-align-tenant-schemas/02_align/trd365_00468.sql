-- Align to baseline — trd365_00468
-- Generated 2026-08-25 from the live definition of trd365_00468.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Run 01_backup/trd365_00468.sql first.

BEGIN;
SET LOCAL search_path = "trd365_00468";


-- ---- add (1) ----------------------------------------------------
ALTER TABLE "trd365_00468"."interactions" ADD COLUMN IF NOT EXISTS "section_percentages" jsonb;

-- ---- widen (6) --------------------------------------------------
ALTER TABLE "trd365_00468"."interactions" ALTER COLUMN "recipient_email" TYPE varchar(255) USING "recipient_email"::varchar(255);
ALTER TABLE "trd365_00468"."interactions" ALTER COLUMN "recipient_name" TYPE varchar(255) USING "recipient_name"::varchar(255);
ALTER TABLE "trd365_00468"."key_contact_details" ALTER COLUMN "key_contact_email" TYPE varchar(255) USING "key_contact_email"::varchar(255);
ALTER TABLE "trd365_00468"."key_contact_details" ALTER COLUMN "key_contact_name" TYPE varchar(255) USING "key_contact_name"::varchar(255);
ALTER TABLE "trd365_00468"."otp_entries" ALTER COLUMN "email" TYPE varchar(255) USING "email"::varchar(255);
ALTER TABLE "trd365_00468"."otp_entries_history" ALTER COLUMN "email" TYPE varchar(255) USING "email"::varchar(255);

COMMIT;
