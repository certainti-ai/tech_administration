-- Align to baseline — trd365_00381
-- Generated 2026-08-25 from the live definition of trd365_00381.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Run 01_backup/trd365_00381.sql first.

BEGIN;
SET LOCAL search_path = "trd365_00381";


-- ---- default (2) ------------------------------------------------
ALTER TABLE "trd365_00381"."case_history_submission" ALTER COLUMN "created_datetime" SET DEFAULT now();
ALTER TABLE "trd365_00381"."case_technical_summary" ALTER COLUMN "created_datetime" SET DEFAULT now();

-- ---- tighten (11) -----------------------------------------------
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."ai_assessment_audit" WHERE "is_four_part_assessment_processed" IS NULL) THEN RAISE EXCEPTION 'ai_assessment_audit.is_four_part_assessment_processed still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."ai_assessment_audit" ALTER COLUMN "is_four_part_assessment_processed" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."comments_attachments" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'comments_attachments.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."comments_attachments" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."comments_attachments" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'comments_attachments.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."comments_attachments" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00381"."comments_attachments" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_attachments" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_attachments.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_attachments" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_attachments" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_attachments.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_attachments" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00381"."task_attachments" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_collaborators" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_collaborators.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_collaborators" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_collaborators" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_collaborators.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_collaborators" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00381"."task_collaborators" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_comments" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_comments.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_comments" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_comments" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_comments.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_comments" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00381"."task_comments" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_tags" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_tags.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_tags" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00381"."task_tags" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_tags.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00381"."task_tags" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00381"."task_tags" ALTER COLUMN "created_datetime" SET DEFAULT now();

COMMIT;
