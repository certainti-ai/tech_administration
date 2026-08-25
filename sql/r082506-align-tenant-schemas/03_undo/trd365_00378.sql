-- Undo — trd365_00378
-- Generated 2026-08-25 from the live definition of trd365_00378.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Restores the column definitions recorded before alignment.
-- Data is not restored: see the note at the foot of this file.

BEGIN;
SET LOCAL search_path = "trd365_00378";

ALTER TABLE "trd365_00378"."task_tags" ALTER COLUMN "created_datetime" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_tags" ALTER COLUMN "created_datetime" DROP DEFAULT;
ALTER TABLE "trd365_00378"."task_tags" ALTER COLUMN "created_by" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_comments" ALTER COLUMN "created_datetime" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_comments" ALTER COLUMN "created_datetime" DROP DEFAULT;
ALTER TABLE "trd365_00378"."task_comments" ALTER COLUMN "created_by" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_collaborators" ALTER COLUMN "created_datetime" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_collaborators" ALTER COLUMN "created_datetime" DROP DEFAULT;
ALTER TABLE "trd365_00378"."task_collaborators" ALTER COLUMN "created_by" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_attachments" ALTER COLUMN "created_datetime" DROP NOT NULL;
ALTER TABLE "trd365_00378"."task_attachments" ALTER COLUMN "created_datetime" DROP DEFAULT;
ALTER TABLE "trd365_00378"."task_attachments" ALTER COLUMN "created_by" DROP NOT NULL;
ALTER TABLE "trd365_00378"."comments_attachments" ALTER COLUMN "created_datetime" DROP NOT NULL;
ALTER TABLE "trd365_00378"."comments_attachments" ALTER COLUMN "created_datetime" DROP DEFAULT;
ALTER TABLE "trd365_00378"."comments_attachments" ALTER COLUMN "created_by" DROP NOT NULL;
ALTER TABLE "trd365_00378"."ai_assessment_audit" ALTER COLUMN "is_four_part_assessment_processed" DROP NOT NULL;
ALTER TABLE "trd365_00378"."case_technical_summary" ALTER COLUMN "created_datetime" DROP DEFAULT;
ALTER TABLE "trd365_00378"."case_history_submission" ALTER COLUMN "created_datetime" DROP DEFAULT;

COMMIT;

-- If a type conversion mangled values, the pre-change data is in
-- trd365_00378.r082506_<table>.  Restoring it is a deliberate act:
--   BEGIN;
--   DELETE FROM "trd365_00378"."<table>";
--   INSERT INTO "trd365_00378"."<table>" SELECT * FROM "trd365_00378"."r082506_<table>";
--   COMMIT;
