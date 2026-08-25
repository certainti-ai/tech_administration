-- Backup — trd365_00476
-- Generated 2026-08-25 from the live definition of trd365_00476.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


BEGIN;
SET LOCAL search_path = "trd365_00476";

-- interactions
CREATE TABLE "trd365_00476"."r082506_interactions" AS SELECT * FROM "trd365_00476"."interactions";
COMMENT ON TABLE "trd365_00476"."r082506_interactions" IS 'r082506 pre-alignment copy of interactions, taken 2026-08-25';

-- key_contact_details
CREATE TABLE "trd365_00476"."r082506_key_contact_details" AS SELECT * FROM "trd365_00476"."key_contact_details";
COMMENT ON TABLE "trd365_00476"."r082506_key_contact_details" IS 'r082506 pre-alignment copy of key_contact_details, taken 2026-08-25';

-- otp_entries
CREATE TABLE "trd365_00476"."r082506_otp_entries" AS SELECT * FROM "trd365_00476"."otp_entries";
COMMENT ON TABLE "trd365_00476"."r082506_otp_entries" IS 'r082506 pre-alignment copy of otp_entries, taken 2026-08-25';

-- otp_entries_history
CREATE TABLE "trd365_00476"."r082506_otp_entries_history" AS SELECT * FROM "trd365_00476"."otp_entries_history";
COMMENT ON TABLE "trd365_00476"."r082506_otp_entries_history" IS 'r082506 pre-alignment copy of otp_entries_history, taken 2026-08-25';

-- Row counts must match before anything is altered.
DO $$
DECLARE t text; a bigint; b bigint;
BEGIN
  FOREACH t IN ARRAY ARRAY['interactions', 'key_contact_details', 'otp_entries', 'otp_entries_history'] LOOP
    EXECUTE format('SELECT count(*) FROM %I.%I', 'trd365_00476', t) INTO a;
    EXECUTE format('SELECT count(*) FROM %I.%I', 'trd365_00476', 'r082506_' || t) INTO b;
    IF a IS DISTINCT FROM b THEN
      RAISE EXCEPTION 'backup row count mismatch for %: % vs %', t, a, b;
    END IF;
  END LOOP;
END $$;

COMMIT;
