-- Undo — trd365_00431
-- Generated 2026-08-25 from the live definition of trd365_00431.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Restores the column definitions recorded before alignment.
-- Data is not restored: see the note at the foot of this file.

BEGIN;
SET LOCAL search_path = "trd365_00431";

ALTER TABLE "trd365_00431"."case_technical_summary" ALTER COLUMN "created_datetime" DROP DEFAULT;

COMMIT;

-- If a type conversion mangled values, the pre-change data is in
-- trd365_00431.r082506_<table>.  Restoring it is a deliberate act:
--   BEGIN;
--   DELETE FROM "trd365_00431"."<table>";
--   INSERT INTO "trd365_00431"."<table>" SELECT * FROM "trd365_00431"."r082506_<table>";
--   COMMIT;
