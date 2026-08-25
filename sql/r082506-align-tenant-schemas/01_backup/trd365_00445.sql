-- Backup — trd365_00445
-- Generated 2026-08-25 from the live definition of trd365_00445.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


BEGIN;
SET LOCAL search_path = "trd365_00445";

-- case_technical_summary
CREATE TABLE "trd365_00445"."r082506_case_technical_summary" AS SELECT * FROM "trd365_00445"."case_technical_summary";
COMMENT ON TABLE "trd365_00445"."r082506_case_technical_summary" IS 'r082506 pre-alignment copy of case_technical_summary, taken 2026-08-25';

-- Row counts must match before anything is altered.
DO $$
DECLARE t text; a bigint; b bigint;
BEGIN
  FOREACH t IN ARRAY ARRAY['case_technical_summary'] LOOP
    EXECUTE format('SELECT count(*) FROM %I.%I', 'trd365_00445', t) INTO a;
    EXECUTE format('SELECT count(*) FROM %I.%I', 'trd365_00445', 'r082506_' || t) INTO b;
    IF a IS DISTINCT FROM b THEN
      RAISE EXCEPTION 'backup row count mismatch for %: % vs %', t, a, b;
    END IF;
  END LOOP;
END $$;

COMMIT;
