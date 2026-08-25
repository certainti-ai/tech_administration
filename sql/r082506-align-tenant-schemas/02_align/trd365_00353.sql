-- Align to baseline — trd365_00353
-- Generated 2026-08-25 from the live definition of trd365_00353.
-- Baseline: trd365_00440.  trd365_00042 is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\set ON_ERROR_STOP on


-- Run 01_backup/trd365_00353.sql first.

BEGIN;
SET LOCAL search_path = "trd365_00353";


-- ---- widen (6 applied, 1 held back) --------------------------------------------------
ALTER TABLE "trd365_00353"."activities" ALTER COLUMN "created_datetime" TYPE timestamp with time zone USING "created_datetime"::timestamp with time zone;
ALTER TABLE "trd365_00353"."activities" ALTER COLUMN "modified_datetime" TYPE timestamp with time zone USING "modified_datetime"::timestamp with time zone;
ALTER TABLE "trd365_00353"."ai_assessment_qre" ALTER COLUMN "created_datetime" TYPE timestamp with time zone USING "created_datetime"::timestamp with time zone;
ALTER TABLE "trd365_00353"."ai_assessment_qre" ALTER COLUMN "modified_datetime" TYPE timestamp with time zone USING "modified_datetime"::timestamp with time zone;
ALTER TABLE "trd365_00353"."case_technical_summary" ALTER COLUMN "created_datetime" TYPE timestamp with time zone USING "created_datetime"::timestamp with time zone;
ALTER TABLE "trd365_00353"."case_technical_summary" ALTER COLUMN "modified_datetime" TYPE timestamp with time zone USING "modified_datetime"::timestamp with time zone;
-- HELD BACK: "status" is the enum enum_webhook_email_history_status here, not a
-- varchar.  Converting it to varchar(20) drops the enum's value constraint, so it
-- is a constraint change rather than a widening.  See held_back.sql.
-- ALTER TABLE "trd365_00353"."webhook_email_history" ALTER COLUMN "status" TYPE varchar(20) USING "status"::varchar(20);

-- ---- loosen (1) -------------------------------------------------
ALTER TABLE "trd365_00353"."project_history" ALTER COLUMN "new_value" DROP NOT NULL;

-- ---- default (1) ------------------------------------------------
ALTER TABLE "trd365_00353"."case_history_submission" ALTER COLUMN "created_datetime" SET DEFAULT now();

-- ---- tighten (12) -----------------------------------------------
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."ai_assessment_audit" WHERE "is_four_part_assessment_processed" IS NULL) THEN RAISE EXCEPTION 'ai_assessment_audit.is_four_part_assessment_processed still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."ai_assessment_audit" ALTER COLUMN "is_four_part_assessment_processed" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."case_technical_summary" WHERE "case_rid" IS NULL) THEN RAISE EXCEPTION 'case_technical_summary.case_rid still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."case_technical_summary" ALTER COLUMN "case_rid" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."comments_attachments" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'comments_attachments.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."comments_attachments" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."comments_attachments" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'comments_attachments.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."comments_attachments" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00353"."comments_attachments" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_attachments" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_attachments.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_attachments" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_attachments" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_attachments.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_attachments" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00353"."task_attachments" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_collaborators" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_collaborators.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_collaborators" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_collaborators" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_collaborators.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_collaborators" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00353"."task_collaborators" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_comments" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_comments.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_comments" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_comments" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_comments.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_comments" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00353"."task_comments" ALTER COLUMN "created_datetime" SET DEFAULT now();
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_tags" WHERE "created_by" IS NULL) THEN RAISE EXCEPTION 'task_tags.created_by still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_tags" ALTER COLUMN "created_by" SET NOT NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM "trd365_00353"."task_tags" WHERE "created_datetime" IS NULL) THEN RAISE EXCEPTION 'task_tags.created_datetime still has NULLs — cannot set NOT NULL'; END IF; END $$;
ALTER TABLE "trd365_00353"."task_tags" ALTER COLUMN "created_datetime" SET NOT NULL;
ALTER TABLE "trd365_00353"."task_tags" ALTER COLUMN "created_datetime" SET DEFAULT now();

COMMIT;

-- ====================================================================
-- HELD BACK — these NARROW the column and can lose data.
-- Measure first, decide, then run by hand.  See held_back.sql.
-- ====================================================================
-- 
-- ---- narrow (4) -------------------------------------------------
-- -- case_technical_summary.eid: varchar(120) -> varchar(50)
-- ALTER TABLE "trd365_00353"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);
-- -- project_fiscal.total_nonlabor_from_prj_res: numeric(18,2) -> integer
-- ALTER TABLE "trd365_00353"."project_fiscal" ALTER COLUMN "total_nonlabor_from_prj_res" TYPE integer USING "total_nonlabor_from_prj_res"::integer;
-- -- webhook_email_history.created_datetime: timestamp with time zone -> timestamp without time zone
-- ALTER TABLE "trd365_00353"."webhook_email_history" ALTER COLUMN "created_datetime" TYPE timestamp without time zone USING "created_datetime"::timestamp without time zone;
-- -- webhook_email_history.uploaded_time: timestamp with time zone -> timestamp without time zone
-- ALTER TABLE "trd365_00353"."webhook_email_history" ALTER COLUMN "uploaded_time" TYPE timestamp without time zone USING "uploaded_time"::timestamp without time zone;
