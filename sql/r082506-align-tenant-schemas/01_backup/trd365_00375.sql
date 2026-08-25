-- Backup — trd365_00375
-- Generated 2026-08-25 from the live definition of trd365_00375.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


BEGIN;
SET LOCAL search_path = "trd365_00375";

-- ai_assessment_audit
CREATE TABLE "trd365_00375"."r082506_ai_assessment_audit" AS SELECT * FROM "trd365_00375"."ai_assessment_audit";
COMMENT ON TABLE "trd365_00375"."r082506_ai_assessment_audit" IS 'r082506 pre-alignment copy of ai_assessment_audit, taken 2026-08-25';

-- case_history_submission
CREATE TABLE "trd365_00375"."r082506_case_history_submission" AS SELECT * FROM "trd365_00375"."case_history_submission";
COMMENT ON TABLE "trd365_00375"."r082506_case_history_submission" IS 'r082506 pre-alignment copy of case_history_submission, taken 2026-08-25';

-- case_technical_summary
CREATE TABLE "trd365_00375"."r082506_case_technical_summary" AS SELECT * FROM "trd365_00375"."case_technical_summary";
COMMENT ON TABLE "trd365_00375"."r082506_case_technical_summary" IS 'r082506 pre-alignment copy of case_technical_summary, taken 2026-08-25';

-- comments_attachments
CREATE TABLE "trd365_00375"."r082506_comments_attachments" AS SELECT * FROM "trd365_00375"."comments_attachments";
COMMENT ON TABLE "trd365_00375"."r082506_comments_attachments" IS 'r082506 pre-alignment copy of comments_attachments, taken 2026-08-25';

-- task_attachments
CREATE TABLE "trd365_00375"."r082506_task_attachments" AS SELECT * FROM "trd365_00375"."task_attachments";
COMMENT ON TABLE "trd365_00375"."r082506_task_attachments" IS 'r082506 pre-alignment copy of task_attachments, taken 2026-08-25';

-- task_collaborators
CREATE TABLE "trd365_00375"."r082506_task_collaborators" AS SELECT * FROM "trd365_00375"."task_collaborators";
COMMENT ON TABLE "trd365_00375"."r082506_task_collaborators" IS 'r082506 pre-alignment copy of task_collaborators, taken 2026-08-25';

-- task_comments
CREATE TABLE "trd365_00375"."r082506_task_comments" AS SELECT * FROM "trd365_00375"."task_comments";
COMMENT ON TABLE "trd365_00375"."r082506_task_comments" IS 'r082506 pre-alignment copy of task_comments, taken 2026-08-25';

-- task_tags
CREATE TABLE "trd365_00375"."r082506_task_tags" AS SELECT * FROM "trd365_00375"."task_tags";
COMMENT ON TABLE "trd365_00375"."r082506_task_tags" IS 'r082506 pre-alignment copy of task_tags, taken 2026-08-25';

-- Row counts must match before anything is altered.
DO $$
DECLARE t text; a bigint; b bigint;
BEGIN
  FOREACH t IN ARRAY ARRAY['ai_assessment_audit', 'case_history_submission', 'case_technical_summary', 'comments_attachments', 'task_attachments', 'task_collaborators', 'task_comments', 'task_tags'] LOOP
    EXECUTE format('SELECT count(*) FROM %I.%I', 'trd365_00375', t) INTO a;
    EXECUTE format('SELECT count(*) FROM %I.%I', 'trd365_00375', 'r082506_' || t) INTO b;
    IF a IS DISTINCT FROM b THEN
      RAISE EXCEPTION 'backup row count mismatch for %: % vs %', t, a, b;
    END IF;
  END LOOP;
END $$;

COMMIT;
