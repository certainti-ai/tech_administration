-- Undo — trd365_00468
-- Generated 2026-08-25 from the live definition of trd365_00468.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Restores the column definitions recorded before alignment.
-- Data is not restored: see the note at the foot of this file.

BEGIN;
SET LOCAL search_path = "trd365_00468";

ALTER TABLE "trd365_00468"."otp_entries_history" ALTER COLUMN "email" TYPE varchar(120) USING "email"::varchar(120);
ALTER TABLE "trd365_00468"."otp_entries" ALTER COLUMN "email" TYPE varchar(120) USING "email"::varchar(120);
ALTER TABLE "trd365_00468"."key_contact_details" ALTER COLUMN "key_contact_name" TYPE varchar(128) USING "key_contact_name"::varchar(128);
ALTER TABLE "trd365_00468"."key_contact_details" ALTER COLUMN "key_contact_email" TYPE varchar(125) USING "key_contact_email"::varchar(125);
ALTER TABLE "trd365_00468"."interactions" ALTER COLUMN "recipient_name" TYPE varchar(50) USING "recipient_name"::varchar(50);
ALTER TABLE "trd365_00468"."interactions" ALTER COLUMN "recipient_email" TYPE varchar(50) USING "recipient_email"::varchar(50);
ALTER TABLE "trd365_00468"."interactions" DROP COLUMN IF EXISTS "section_percentages";

COMMIT;

-- If a type conversion mangled values, the pre-change data is in
-- trd365_00468.r082506_<table>.  Restoring it is a deliberate act:
--   BEGIN;
--   DELETE FROM "trd365_00468"."<table>";
--   INSERT INTO "trd365_00468"."<table>" SELECT * FROM "trd365_00468"."r082506_<table>";
--   COMMIT;
