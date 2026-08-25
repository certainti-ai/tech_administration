-- Align to baseline — trd365_00388
-- Generated 2026-08-25 from the live definition of trd365_00388.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Run 01_backup/trd365_00388.sql first.

BEGIN;
SET LOCAL search_path = "trd365_00388";


-- ---- widen (2) --------------------------------------------------
ALTER TABLE "trd365_00388"."case_technical_summary" ALTER COLUMN "created_datetime" TYPE timestamp with time zone USING "created_datetime"::timestamp with time zone;
ALTER TABLE "trd365_00388"."case_technical_summary" ALTER COLUMN "modified_datetime" TYPE timestamp with time zone USING "modified_datetime"::timestamp with time zone;

-- ---- tighten (2) ------------------------------------------------
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00388"."ai_assessment_audit" WHERE "is_four_part_assessment_processed" IS NULL) THEN RAISE EXCEPTION 'ai_assessment_audit.is_four_part_assessment_processed still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00388"."ai_assessment_audit" ALTER COLUMN "is_four_part_assessment_processed" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00388"."case_technical_summary" WHERE "case_rid" IS NULL) THEN RAISE EXCEPTION 'case_technical_summary.case_rid still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00388"."case_technical_summary" ALTER COLUMN "case_rid" SET NOT NULL;

COMMIT;

-- ====================================================================
-- HELD BACK — these NARROW the column and can lose data.
-- Measure first, decide, then run by hand.  See held_back.sql.
-- ====================================================================
-- 
-- ---- narrow (1) -------------------------------------------------
-- -- case_technical_summary.eid: varchar(120) -> varchar(50)
-- ALTER TABLE "trd365_00388"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);
