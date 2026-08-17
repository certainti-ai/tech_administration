-- =================================================================
-- DELETE MILESTONE TASKS
--
-- Purpose : Safely delete all tasks (and their child records) that
--           belong to a specific Milestone within a specific Case.
--           The Milestone record itself is NOT deleted.
--
-- Usage   : Set the three variables at the top of the DO block:
--             v_schema        – tenant schema  (e.g. 'trd365_000001')
--             v_case_rid      – case.rid        (e.g. 'DEV-abc123')
--             v_milestone_rid – case_milestone.rid (e.g. 'DEV-ml456')
--
-- Run     : psql -h <host> -U <user> -d thinkrd365_org \
--               -f 03_delete_milestone_tasks.sql
--
-- Safety  : Runs inside a single TRANSACTION.
--           Set dry_run := TRUE to preview row counts without
--           making any changes.
--
-- Delete order (children first):
--   1. checklist_items       (via checklists.attach_to = task.rid)
--   2. checklists            (attach_to = task.rid, attachment_level = 'task')
--   3. comments_attachments  (task_rid  = task.rid)
--   4. task_comments         (task_rid  = task.rid)
--   5. task_attachments      (task_rid  = task.rid)
--   6. task_collaborators    (task_rid  = task.rid)
--   7. task_tags             (task_rid  = task.rid)
--   8. task_history          (task_rid  = task.rid)
--   9. task_summary          (task_rid  = task.rid)
--  10. case_history          (task_rid  = task.rid)
--  11. case_task_dependency_mapping (source_rid or target_rid = task.rid)
--  12. case_task             (milestone_template_rid = milestone.rid)
-- =================================================================

DO $$
DECLARE
    -- ---------------------------------------------------------------
    -- CONFIGURE THESE THREE VALUES BEFORE RUNNING
    -- ---------------------------------------------------------------
    v_schema        TEXT    := 'trd365_00414';         -- tenant schema name
    v_case_rid      TEXT    := 'P001-76885c9c-bd88-442c-955e-5f0b6c0e20ed';
    v_milestone_rid TEXT    := 'P001-30104889-1cc7-470c-8128-099fe0192100';
 --   v_milestone_rid TEXT    := 'U001-7654125c-f0e9-464e-8bdb-2be82771f920';

    dry_run         BOOLEAN := FALSE;              -- FALSE to actually delete
    -- ---------------------------------------------------------------

    v_task_rids              TEXT[];
    v_checklist_rids         TEXT[];
    v_check                  TEXT;
    -- Resolved rid from case_milestone (may differ from v_milestone_rid if
    -- the caller supplied an eid instead of a rid).
    v_milestone_rid_actual   TEXT;
    v_deleted_checklist_items   BIGINT := 0;
    v_deleted_checklists        BIGINT := 0;
    v_deleted_comments_attach   BIGINT := 0;
    v_deleted_task_comments     BIGINT := 0;
    v_deleted_task_attachments  BIGINT := 0;
    v_deleted_task_collaborators BIGINT := 0;
    v_deleted_task_tags         BIGINT := 0;
    v_deleted_task_history      BIGINT := 0;
    v_deleted_task_summary      BIGINT := 0;
    v_deleted_case_history      BIGINT := 0;
    v_deleted_dep_mapping       BIGINT := 0;
    v_deleted_tasks             BIGINT := 0;
BEGIN

    -- ------------------------------------------------------------------
    -- STEP 0 · Validate inputs and confirm milestone exists
    -- ------------------------------------------------------------------
    IF v_schema LIKE '%REPLACE_ME%' THEN
        RAISE EXCEPTION 'v_schema has not been set. Replace ''trd365_REPLACE_ME'' with your actual tenant schema name (e.g. trd365_D001).';
    END IF;

    -- Confirm the milestone exists (searches eid then rid; no case_rid filter here
    -- so the error message clearly distinguishes "bad milestone ID" from "wrong case").
    -- If the schema or table does not exist, PostgreSQL will raise a
    -- clear "relation does not exist" error automatically.
    EXECUTE format(
        'SELECT rid FROM %I.case_milestone
         WHERE  (eid = $1 OR rid = $1)
         LIMIT 1',
        v_schema
    ) INTO v_milestone_rid_actual USING v_milestone_rid;

    IF v_milestone_rid_actual IS NULL THEN
        RAISE EXCEPTION
            'Milestone eid/rid=% not found in schema=%. '
            'Check the identifier against: SELECT eid, rid, milestone_name, case_rid FROM %I.case_milestone WHERE eid = ''%'' OR rid = ''%'';',
            v_milestone_rid, v_schema, v_schema, v_milestone_rid, v_milestone_rid;
    END IF;

    RAISE NOTICE 'Resolved milestone eid/rid=% → rid=%', v_milestone_rid, v_milestone_rid_actual;

    -- ------------------------------------------------------------------
    -- STEP 1 · Collect the task RIDs to be deleted
    -- ------------------------------------------------------------------
    -- case_task.milestone_template_rid joins on case_milestone.rid
    -- so use v_milestone_rid_actual (the resolved rid) here.
    EXECUTE format(
        'SELECT ARRAY(
            SELECT rid
            FROM   %I.case_task
            WHERE  milestone_template_rid = $1
              AND  case_rid               = $2
        )',
        v_schema
    ) INTO v_task_rids USING v_milestone_rid_actual, v_case_rid;

    IF v_task_rids IS NULL OR array_length(v_task_rids, 1) IS NULL THEN
        RAISE NOTICE 'No tasks found for milestone rid=% in case_rid=%. Nothing to delete.',
            v_milestone_rid_actual, v_case_rid;
        RETURN;
    END IF;

    RAISE NOTICE '% task(s) targeted for deletion under milestone rid=% / case_rid=%',
        array_length(v_task_rids, 1), v_milestone_rid_actual, v_case_rid;

    IF dry_run THEN
        RAISE NOTICE '[DRY-RUN] Task RIDs: %', v_task_rids;
    END IF;

    -- ------------------------------------------------------------------
    -- STEP 2 · Collect checklist RIDs attached to these tasks
    -- ------------------------------------------------------------------
    EXECUTE format(
        'SELECT ARRAY(
            SELECT rid
            FROM   %I.checklists
            WHERE  attach_to         = ANY($1)
              AND  attachment_level  = ''task''
              AND  case_rid          = $2
        )',
        v_schema
    ) INTO v_checklist_rids USING v_task_rids, v_case_rid;

    -- ------------------------------------------------------------------
    -- STEP 3 · Delete in child-first order (skip when dry_run = TRUE)
    -- ------------------------------------------------------------------

    -- 3-1  checklist_items
    IF v_checklist_rids IS NOT NULL AND array_length(v_checklist_rids, 1) > 0 THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.checklist_items
                    WHERE checklist_rid = ANY($1)
                    RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_checklist_items USING v_checklist_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.checklist_items
                 WHERE checklist_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_checklist_items USING v_checklist_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] checklist_items:            %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_checklist_items;

    -- 3-2  checklists
    IF v_checklist_rids IS NOT NULL AND array_length(v_checklist_rids, 1) > 0 THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.checklists
                    WHERE  attach_to        = ANY($1)
                      AND  attachment_level = ''task''
                      AND  case_rid         = $2
                    RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_checklists USING v_task_rids, v_case_rid;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.checklists
                 WHERE  attach_to        = ANY($1)
                   AND  attachment_level = ''task''
                   AND  case_rid         = $2',
                v_schema
            ) INTO v_deleted_checklists USING v_task_rids, v_case_rid;
        END IF;
    END IF;
    RAISE NOTICE '[%] checklists:                 %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_checklists;

    -- 3-3  comments_attachments
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'comments_attachments') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.comments_attachments WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_comments_attach USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.comments_attachments WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_comments_attach USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] comments_attachments:       %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_comments_attach;

    -- 3-4  task_comments
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'task_comments') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.task_comments WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_task_comments USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.task_comments WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_task_comments USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] task_comments:              %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_task_comments;

    -- 3-5  task_attachments
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'task_attachments') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.task_attachments WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_task_attachments USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.task_attachments WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_task_attachments USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] task_attachments:           %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_task_attachments;

    -- 3-6  task_collaborators
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'task_collaborators') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.task_collaborators WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_task_collaborators USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.task_collaborators WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_task_collaborators USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] task_collaborators:         %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_task_collaborators;

    -- 3-7  task_tags
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'task_tags') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.task_tags WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_task_tags USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.task_tags WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_task_tags USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] task_tags:                  %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_task_tags;

    -- 3-8  task_history
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'task_history') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.task_history WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_task_history USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.task_history WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_task_history USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] task_history:               %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_task_history;

    -- 3-9  task_summary
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'task_summary') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.task_summary WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_task_summary USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.task_summary WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_task_summary USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] task_summary:               %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_task_summary;

    -- 3-10  case_history (task-level entries)
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'case_history') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.case_history WHERE task_rid = ANY($1) RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_case_history USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.case_history WHERE task_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_case_history USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] case_history (task rows):   %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_case_history;

    -- 3-11  case_task_dependency_mapping (source or target = task.rid)
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = v_schema AND tablename = 'case_task_dependency_mapping') THEN
        IF NOT dry_run THEN
            EXECUTE format(
                'WITH deleted AS (
                    DELETE FROM %I.case_task_dependency_mapping
                    WHERE  source_rid = ANY($1)
                       OR  target_rid = ANY($1)
                    RETURNING 1
                ) SELECT COUNT(*) FROM deleted',
                v_schema
            ) INTO v_deleted_dep_mapping USING v_task_rids;
        ELSE
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.case_task_dependency_mapping
                 WHERE  source_rid = ANY($1) OR target_rid = ANY($1)',
                v_schema
            ) INTO v_deleted_dep_mapping USING v_task_rids;
        END IF;
    END IF;
    RAISE NOTICE '[%] case_task_dependency_mapping: %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_dep_mapping;

    -- 3-12  case_task (the tasks themselves)
    IF NOT dry_run THEN
        EXECUTE format(
            'WITH deleted AS (
                DELETE FROM %I.case_task
                WHERE  milestone_template_rid = $1
                  AND  case_rid               = $2
                RETURNING 1
            ) SELECT COUNT(*) FROM deleted',
            v_schema
        ) INTO v_deleted_tasks USING v_milestone_rid_actual, v_case_rid;
    ELSE
        EXECUTE format(
            'SELECT COUNT(*) FROM %I.case_task
             WHERE  milestone_template_rid = $1
               AND  case_rid               = $2',
            v_schema
        ) INTO v_deleted_tasks USING v_milestone_rid_actual, v_case_rid;
    END IF;
    RAISE NOTICE '[%] case_task:                  %',
        CASE WHEN dry_run THEN 'DRY-RUN' ELSE 'DELETED' END, v_deleted_tasks;

    -- ------------------------------------------------------------------
    -- SUMMARY
    -- ------------------------------------------------------------------
    RAISE NOTICE '=== SUMMARY (schema=%, milestone_rid=%, case_rid=%) ===',
        v_schema, v_milestone_rid, v_case_rid;
    RAISE NOTICE '  checklist_items             : %', v_deleted_checklist_items;
    RAISE NOTICE '  checklists                  : %', v_deleted_checklists;
    RAISE NOTICE '  comments_attachments        : %', v_deleted_comments_attach;
    RAISE NOTICE '  task_comments               : %', v_deleted_task_comments;
    RAISE NOTICE '  task_attachments            : %', v_deleted_task_attachments;
    RAISE NOTICE '  task_collaborators          : %', v_deleted_task_collaborators;
    RAISE NOTICE '  task_tags                   : %', v_deleted_task_tags;
    RAISE NOTICE '  task_history                : %', v_deleted_task_history;
    RAISE NOTICE '  task_summary                : %', v_deleted_task_summary;
    RAISE NOTICE '  case_history (task rows)    : %', v_deleted_case_history;
    RAISE NOTICE '  case_task_dependency_mapping: %', v_deleted_dep_mapping;
    RAISE NOTICE '  case_task                   : %', v_deleted_tasks;

    IF dry_run THEN
        RAISE NOTICE '*** DRY-RUN complete – no rows were modified. Set dry_run := FALSE to apply. ***';
    END IF;

END $$;
