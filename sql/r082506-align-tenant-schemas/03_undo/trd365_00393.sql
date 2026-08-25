-- Undo — trd365_00393
-- Generated 2026-08-25 from the live definition of trd365_00393.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Restores the column definitions recorded before alignment.
-- Data is not restored: see the note at the foot of this file.

BEGIN;
SET LOCAL search_path = "trd365_00393";

ALTER TABLE "trd365_00393"."case_technical_summary" ALTER COLUMN "case_rid" DROP NOT NULL;
ALTER TABLE "trd365_00393"."ai_assessment_audit" ALTER COLUMN "is_four_part_assessment_processed" DROP NOT NULL;
ALTER TABLE "trd365_00393"."case_technical_summary" ALTER COLUMN "modified_datetime" TYPE timestamp without time zone USING "modified_datetime"::timestamp without time zone;
ALTER TABLE "trd365_00393"."case_technical_summary" ALTER COLUMN "created_datetime" TYPE timestamp without time zone USING "created_datetime"::timestamp without time zone;

COMMIT;

-- If a type conversion mangled values, the pre-change data is in
-- trd365_00393.r082506_<table>.  Restoring it is a deliberate act:
--   BEGIN;
--   DELETE FROM "trd365_00393"."<table>";
--   INSERT INTO "trd365_00393"."<table>" SELECT * FROM "trd365_00393"."r082506_<table>";
--   COMMIT;
