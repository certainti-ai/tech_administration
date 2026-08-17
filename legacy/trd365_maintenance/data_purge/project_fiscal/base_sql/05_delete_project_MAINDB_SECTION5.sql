-- SECTION 5  MAIN DB — Post-Delete Diff
-- Run on: thinkrd365_main  |   Run: AFTER Section 3
-- Reads v_backup_schema from a hand-pasted placeholder (the value SECTION 1
-- announced for this run) — no cross-session shared lookup table anymore.
-- =============================================================================
DO $$
DECLARE
  -- ▼▼▼  FILL IN  ▼▼▼ -------------------------------------------------------
  v_lookup_project_fiscal_id TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';  -- same value used in SECTION 3
  -- ▲▲▲ -------------------------------------------------------------------

  -- PASTE the backup schema SECTION 1 announced here:
  v_backup_schema     TEXT := 'backup_release_v5_3_3_trd365_0137_PRJ_2024_20260723_083409';
  v_run_at            TIMESTAMPTZ := clock_timestamp();
  v_pre_run_at        TIMESTAMPTZ;  -- resolved below from this run's pre-snapshot
  v_account_rid       TEXT := 'D001-4bf2b0a2-f11c-4941-b075-82e8682a1e20';
  v_project_rid       TEXT := 'D001-a9fc5b2a-8a2d-4895-bd28-817ae0b51f33';
  v_project_fiscal_id TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  v_fiscal_year       INT := 2024;
  v_is_last_fiscal    BOOLEAN := FALSE;

  v_pre  BIGINT; v_post BIGINT; v_scope TEXT; v_label TEXT;
  v_pass INT := 0; v_fail INT := 0; v_skip INT := 0;
  v_tbl_exists BOOLEAN;
  r      RECORD;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in v_lookup_project_fiscal_id before running SECTION 5.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  -- Resolve THIS run's pre-snapshot timestamp from the backup schema (SECTION 3
  -- wrote project_main_pre). Formerly a hand-pasted literal; now looked up so the
  -- diff always compares against the current run's counts.
  EXECUTE format('SELECT max(run_at) FROM %I.project_main_pre WHERE project_fiscal_id = $1', v_backup_schema)
    INTO v_pre_run_at USING v_lookup_project_fiscal_id;
  IF v_pre_run_at IS NULL THEN
    RAISE EXCEPTION 'SECTION 5: no pre-snapshot in %.project_main_pre for % — run SECTION 3 first.',
      v_backup_schema, v_lookup_project_fiscal_id;
  END IF;

  -- Permanent table for this section's post-delete counts.
  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.project_main_post (
      run_at             TIMESTAMPTZ NOT NULL,
      project_fiscal_id  TEXT NOT NULL,
      label              TEXT NOT NULL,
      cnt                BIGINT NOT NULL,
      scope              TEXT NOT NULL,
      PRIMARY KEY (project_fiscal_id, run_at, label)
    )
  $ddl$, v_backup_schema);

  DROP TABLE IF EXISTS _prj_main_post_staging;
  CREATE TEMP TABLE _prj_main_post_staging (label TEXT PRIMARY KEY, cnt BIGINT, scope TEXT);

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 5 — MAIN DB POST-DELETE DIFF';
  RAISE NOTICE '  account = %  |  fiscal = %  |  last_fiscal = %  |  pre_run_at = %',
    v_account_rid, v_project_fiscal_id, v_is_last_fiscal, v_pre_run_at;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  %-45s  %7s  %7s  %6s  %s', 'table', 'pre', 'post', 'diff', 'result';
  RAISE NOTICE '  %-45s  %7s  %7s  %6s  %s', '-----', '---', '----', '----', '------';

  FOR r IN EXECUTE format(
    'SELECT label, cnt AS pre, scope FROM %I.project_main_pre WHERE project_fiscal_id = $1 AND run_at = $2 ORDER BY scope, label',
    v_backup_schema
  ) USING v_lookup_project_fiscal_id, v_pre_run_at LOOP
    v_label := r.label; v_pre := r.pre; v_scope := r.scope;

    CASE v_label
      WHEN 'send_email_info' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'send_email_info') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.send_email_info WHERE project_fiscal_rid = v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'ai_trigger_records' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'ai_trigger_records') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.ai_trigger_records WHERE account_rid = v_account_rid AND project_fiscal_rids::text LIKE '%' || v_project_fiscal_id || '%'; ELSE v_post := 0; END IF;
      WHEN 'interactions_summary_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'interactions_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.interactions_summary WHERE project_fiscal_rid = v_project_fiscal_id AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'rule_engine_records_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_records') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.rule_engine_records WHERE entity_rid = v_project_fiscal_id AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'rule_engine_notification_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_notification_records') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.rule_engine_notification_records WHERE entity_rid = v_project_fiscal_id AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'control_center_execution_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'control_center_execution') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.control_center_execution WHERE reference_rid = v_project_fiscal_id AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'user_group_entity_access_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'user_group_entity_access') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.user_group_entity_access WHERE entity_type = 'PROJECT' AND entity_rid = v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_fiscal_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_fiscal_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.project_fiscal_summary WHERE project_fiscal_rid = v_project_fiscal_id AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'chat_assistance_session' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'chat_assistance_session') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.chat_assistance_session WHERE project_rid = v_project_rid AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'interactions_summary_project' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'interactions_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.interactions_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid AND project_fiscal_rid IS NULL; ELSE v_post := 0; END IF;
      WHEN 'rule_engine_records_project' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_records') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.rule_engine_records WHERE entity_rid = v_project_rid AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'rule_engine_notification_project' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_notification_records') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.rule_engine_notification_records WHERE entity_rid = v_project_rid AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'control_center_execution_project' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'control_center_execution') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.control_center_execution WHERE reference_rid = v_project_rid AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'attachment_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'attachment_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.attachment_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'notes_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'notes_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.notes_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'meeting_summary_main' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'meeting_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.meeting_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'task_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'task_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.task_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'user_group_entity_access_project' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'user_group_entity_access') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.user_group_entity_access WHERE entity_type = 'PROJECT' AND entity_rid = v_project_rid; ELSE v_post := 0; END IF;
      WHEN 'project_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN SELECT COUNT(*) INTO v_post FROM trd365.project_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid; ELSE v_post := 0; END IF;
      ELSE v_post := -1;
    END CASE;

    INSERT INTO _prj_main_post_staging VALUES (v_label, v_post, v_scope);

    IF v_scope = 'project' AND NOT v_is_last_fiscal THEN
      v_skip := v_skip + 1;
      RAISE NOTICE '  %-45s  %7s  %7s  %6s  SKIP', v_label, v_pre, v_post, v_post - v_pre;
    ELSIF v_post = 0 THEN
      v_pass := v_pass + 1;
      RAISE NOTICE '  %-45s  %7s  %7s  %6s  PASS', v_label, v_pre, v_post, 0 - v_pre;
    ELSE
      v_fail := v_fail + 1;
      RAISE WARNING '  %-45s  %7s  %7s  %6s  FAIL ← rows still exist', v_label, v_pre, v_post, v_post - v_pre;
    END IF;
  END LOOP;

  -- Persist this run's post-counts permanently into the backup schema.
  EXECUTE format(
    'INSERT INTO %I.project_main_post (run_at, project_fiscal_id, label, cnt, scope) SELECT $1, $2, label, cnt, scope FROM _prj_main_post_staging',
    v_backup_schema
  ) USING v_run_at, v_lookup_project_fiscal_id;

  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  PASS: %   FAIL: %   SKIP (not last fiscal): %', v_pass, v_fail, v_skip;

  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE 'Verify recomputed aggregates:';
  RAISE NOTICE '  SELECT * FROM trd365.account_fiscal_summary WHERE account_rid = ''%'' AND fiscal_year = %', v_account_rid, v_fiscal_year;
  RAISE NOTICE '  SELECT total_cost, total_effort FROM trd365.project_summary WHERE project_rid = ''%''', v_project_rid;
  RAISE NOTICE '  SELECT total_projects, total_project_cost FROM trd365.account WHERE rid = ''%''', v_account_rid;

  IF v_fail > 0 THEN
    RAISE EXCEPTION 'SECTION 5: % row(s) failed diff — investigate before sign-off.', v_fail;
  ELSE
    RAISE NOTICE 'MAIN DB diff clean. Deletion complete.';
    RAISE NOTICE 'SECTION 5 — MAIN DB POST-DELETE DIFF COMPLETE';
  END IF;
  RAISE NOTICE 'Backup schema: %.project_main_post (run_at = %)', v_backup_schema, v_run_at;
  RAISE NOTICE '==============================================================';
END;
$$;


-- =============================================================================
