-- Align to baseline — trd365_00445
-- Generated 2026-08-25 from the live definition of trd365_00445.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Run 01_backup/trd365_00445.sql first.

BEGIN;
SET LOCAL search_path = "trd365_00445";


-- ---- default (1) ------------------------------------------------
ALTER TABLE "trd365_00445"."case_technical_summary" ALTER COLUMN "created_datetime" SET DEFAULT now();

COMMIT;
