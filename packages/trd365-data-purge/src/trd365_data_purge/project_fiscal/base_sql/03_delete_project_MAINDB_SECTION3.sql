-- SECTION 3  MAIN DB — Pre-Backup Snapshot + Delete
-- Run on: thinkrd365_main  |   Run: AFTER Section 2
-- =============================================================================
DO $$
DECLARE
  -- ▼▼▼  FILL IN THESE VALUES  ▼▼▼ ------------------------------------------
  v_account_rid       TEXT    := 'D001-4bf2b0a2-f11c-4941-b075-82e8682a1e20';
  v_project_rid       TEXT    := 'D001-a9fc5b2a-8a2d-4895-bd28-817ae0b51f33';
  v_project_fiscal_id TEXT    := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  v_fiscal_year       INT     := 2024;
  v_is_last_fiscal    BOOLEAN := FALSE;
  -- ▲▲▲ -------------------------------------------------------------------

  -- PASTE the backup schema SECTION 1 announced here:
  v_backup_schema TEXT := 'backup_release_v5_3_3_trd365_0137_PRJ_2024_20260723_083409';
  v_run_at        TIMESTAMPTZ := clock_timestamp();

  v_cnt        BIGINT;
  v_rows       INT;
  v_tbl_exists BOOLEAN;
  r            RECORD;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in input values before running SECTION 3.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  -- Backup schema for this run was created by SECTION 1; reused here (not re-created).
  EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_backup_schema);

  -- Persist this run's inputs for record-keeping (SECTION 5 no longer reads
  -- them back — v_backup_schema is now hand-carried between sections).
  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.project_main_inputs (
      run_at             TIMESTAMPTZ NOT NULL,
      account_rid        TEXT NOT NULL,
      project_rid        TEXT NOT NULL,
      project_fiscal_id  TEXT NOT NULL,
      fiscal_year        INT NOT NULL,
      is_last_fiscal     BOOLEAN NOT NULL,
      PRIMARY KEY (project_fiscal_id, run_at)
    )
  $ddl$, v_backup_schema);

  EXECUTE format(
    'INSERT INTO %I.project_main_inputs (run_at, account_rid, project_rid, project_fiscal_id, fiscal_year, is_last_fiscal) VALUES ($1,$2,$3,$4,$5,$6)',
    v_backup_schema
  ) USING v_run_at, v_account_rid, v_project_rid, v_project_fiscal_id, v_fiscal_year, v_is_last_fiscal;

  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.project_main_pre (
      run_at             TIMESTAMPTZ NOT NULL,
      project_fiscal_id  TEXT NOT NULL,
      label              TEXT NOT NULL,
      cnt                BIGINT NOT NULL,
      scope              TEXT NOT NULL,
      PRIMARY KEY (project_fiscal_id, run_at, label)
    )
  $ddl$, v_backup_schema);

  -- ── Pre-backup snapshot ──────────────────────────────────────────────────

  -- Session-local staging table (mirrors the permanent one for this run) so
  -- the RAISE NOTICE summary loop below can read back what was just written.
  DROP TABLE IF EXISTS _prj_main_pre;
  CREATE TEMP TABLE _prj_main_pre (label TEXT PRIMARY KEY, cnt BIGINT, scope TEXT);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'send_email_info') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.send_email_info WHERE project_fiscal_rid = v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('send_email_info', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'ai_trigger_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.ai_trigger_records WHERE account_rid = v_account_rid AND project_fiscal_rids::text LIKE '%' || v_project_fiscal_id || '%'; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('ai_trigger_records', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'interactions_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.interactions_summary WHERE project_fiscal_rid = v_project_fiscal_id AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('interactions_summary_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.rule_engine_records WHERE entity_rid = v_project_fiscal_id AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('rule_engine_records_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_notification_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.rule_engine_notification_records WHERE entity_rid = v_project_fiscal_id AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('rule_engine_notification_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'control_center_execution') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.control_center_execution WHERE reference_rid = v_project_fiscal_id AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('control_center_execution_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'user_group_entity_access') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.user_group_entity_access WHERE entity_type = 'PROJECT' AND entity_rid = v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('user_group_entity_access_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_fiscal_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.project_fiscal_summary WHERE project_fiscal_rid = v_project_fiscal_id AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('project_fiscal_summary', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'chat_assistance_session') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.chat_assistance_session WHERE project_rid = v_project_rid AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('chat_assistance_session', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'interactions_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.interactions_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid AND project_fiscal_rid IS NULL; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('interactions_summary_project', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.rule_engine_records WHERE entity_rid = v_project_rid AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('rule_engine_records_project', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_notification_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.rule_engine_notification_records WHERE entity_rid = v_project_rid AND entity_type = 'PROJECT' AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('rule_engine_notification_project', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'control_center_execution') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.control_center_execution WHERE reference_rid = v_project_rid AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('control_center_execution_project', v_cnt, 'project');

  -- Matched by attach_to IN (project_rid, project_fiscal_id), not also
  -- filtered on attachment_level — see SECTION 3 delete comment.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'attachment_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.attachment_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('attachment_summary', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'notes_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.notes_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('notes_summary', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'meeting_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.meeting_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('meeting_summary_main', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'task_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.task_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('task_summary', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'user_group_entity_access') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.user_group_entity_access WHERE entity_type = 'PROJECT' AND entity_rid = v_project_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('user_group_entity_access_project', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN SELECT COUNT(*) INTO v_cnt FROM trd365.project_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_main_pre VALUES ('project_summary', v_cnt, 'project');

  -- Persist this run's pre-counts permanently into the backup schema.
  EXECUTE format(
    'INSERT INTO %I.project_main_pre (run_at, project_fiscal_id, label, cnt, scope) SELECT $1, $2, label, cnt, scope FROM _prj_main_pre',
    v_backup_schema
  ) USING v_run_at, v_project_fiscal_id;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 3 — MAIN DB PRE-BACKUP SNAPSHOT';
  RAISE NOTICE '  account = %  |  fiscal = %  |  last_fiscal = %',
    v_account_rid, v_project_fiscal_id, v_is_last_fiscal;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  %-45s  %8s  %s', 'table', 'pre_count', 'scope';
  FOR r IN SELECT label, cnt, scope FROM _prj_main_pre ORDER BY scope, label LOOP
    RAISE NOTICE '  %-45s  %8s  %s', r.label, r.cnt,
      CASE r.scope WHEN 'fiscal' THEN '(always deleted)' ELSE '(last fiscal only)' END;
  END LOOP;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE 'Aggregate before-values (record manually):';
  RAISE NOTICE '  SELECT * FROM trd365.account_fiscal_summary WHERE account_rid = ''%'' AND fiscal_year = %', v_account_rid, v_fiscal_year;
  RAISE NOTICE '  SELECT total_cost, total_effort FROM trd365.project_summary WHERE project_rid = ''%''', v_project_rid;
  RAISE NOTICE '  SELECT total_projects, total_project_cost FROM trd365.account WHERE rid = ''%''', v_account_rid;
  RAISE NOTICE '==============================================================';

  -- ── Delete ───────────────────────────────────────────────────────────────

  RAISE NOTICE 'SECTION 3 — MAIN DB DELETE STARTED';

  -- Each DELETE below is preceded by a backup step: create
  -- <v_backup_schema>.bak_main_<label> (mirroring the source table's
  -- columns, plus _backup_run_at/_backup_project_fiscal_id), then INSERT
  -- INTO it a SELECT using the EXACT same filter as the DELETE that follows.

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'send_email_info') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_send_email_info (LIKE trd365.send_email_info INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_send_email_info ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format('INSERT INTO %I.bak_main_send_email_info SELECT t.*, $1, $2 FROM trd365.send_email_info t WHERE t.project_fiscal_rid = $2', v_backup_schema) USING v_run_at, v_project_fiscal_id;
    DELETE FROM trd365.send_email_info WHERE project_fiscal_rid = v_project_fiscal_id; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P1]  Backed up + deleted send_email_info: %', v_rows;
  ELSE RAISE NOTICE '[P1]  skip send_email_info'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'ai_trigger_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_ai_trigger_records (LIKE trd365.ai_trigger_records INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_ai_trigger_records ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_ai_trigger_records SELECT t.*, $1, $2 FROM trd365.ai_trigger_records t WHERE t.account_rid = $3 AND t.project_fiscal_rids::text LIKE '%%' || $2 || '%%'$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    DELETE FROM trd365.ai_trigger_records WHERE account_rid = v_account_rid AND project_fiscal_rids::text LIKE '%' || v_project_fiscal_id || '%'; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P2]  Backed up + deleted ai_trigger_records: %', v_rows;
  ELSE RAISE NOTICE '[P2]  skip ai_trigger_records'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'interactions_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_interactions_summary_fiscal (LIKE trd365.interactions_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_interactions_summary_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format('INSERT INTO %I.bak_main_interactions_summary_fiscal SELECT t.*, $1, $2 FROM trd365.interactions_summary t WHERE t.project_fiscal_rid = $2 AND t.account_rid = $3', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    DELETE FROM trd365.interactions_summary WHERE project_fiscal_rid = v_project_fiscal_id AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P3]  Backed up + deleted interactions_summary (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[P3]  skip interactions_summary'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_rule_engine_records_fiscal (LIKE trd365.rule_engine_records INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_rule_engine_records_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_rule_engine_records_fiscal SELECT t.*, $1, $2 FROM trd365.rule_engine_records t WHERE t.entity_rid = $2 AND t.entity_type = 'PROJECT' AND t.account_rid = $3$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    DELETE FROM trd365.rule_engine_records WHERE entity_rid = v_project_fiscal_id AND entity_type = 'PROJECT' AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P4]  Backed up + deleted rule_engine_records (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[P4]  skip rule_engine_records'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_notification_records') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_rule_engine_notification_fiscal (LIKE trd365.rule_engine_notification_records INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_rule_engine_notification_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_rule_engine_notification_fiscal SELECT t.*, $1, $2 FROM trd365.rule_engine_notification_records t WHERE t.entity_rid = $2 AND t.entity_type = 'PROJECT' AND t.account_rid = $3$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    DELETE FROM trd365.rule_engine_notification_records WHERE entity_rid = v_project_fiscal_id AND entity_type = 'PROJECT' AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P5]  Backed up + deleted rule_engine_notification_records (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[P5]  skip rule_engine_notification_records'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'control_center_execution') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_control_center_execution_fiscal (LIKE trd365.control_center_execution INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_control_center_execution_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    -- duration_ms is a GENERATED ALWAYS column on the source table; the LIKE
    -- clause copies that generation expression, but INSERT ... SELECT t.*
    -- cannot write to a generated column. Drop the expression on the backup
    -- copy only, so it becomes a plain writable snapshot column.
    BEGIN
      EXECUTE format('ALTER TABLE %I.bak_main_control_center_execution_fiscal ALTER COLUMN duration_ms DROP EXPRESSION IF EXISTS', v_backup_schema);
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
    EXECUTE format('INSERT INTO %I.bak_main_control_center_execution_fiscal SELECT t.*, $1, $2 FROM trd365.control_center_execution t WHERE t.reference_rid = $2 AND t.account_rid = $3', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    DELETE FROM trd365.control_center_execution WHERE reference_rid = v_project_fiscal_id AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P6]  Backed up + deleted control_center_execution (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[P6]  skip control_center_execution'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'user_group_entity_access') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_user_group_entity_access_fiscal (LIKE trd365.user_group_entity_access INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_user_group_entity_access_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_user_group_entity_access_fiscal SELECT t.*, $1, $2 FROM trd365.user_group_entity_access t WHERE t.entity_type = 'PROJECT' AND t.entity_rid = $2$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id;
    DELETE FROM trd365.user_group_entity_access WHERE entity_type = 'PROJECT' AND entity_rid = v_project_fiscal_id; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P7]  Backed up + deleted user_group_entity_access (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[P7]  skip user_group_entity_access'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_fiscal_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_project_fiscal_summary (LIKE trd365.project_fiscal_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_project_fiscal_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format('INSERT INTO %I.bak_main_project_fiscal_summary SELECT t.*, $1, $2 FROM trd365.project_fiscal_summary t WHERE t.project_fiscal_rid = $2 AND t.account_rid = $3', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    DELETE FROM trd365.project_fiscal_summary WHERE project_fiscal_rid = v_project_fiscal_id AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P8]  Backed up + deleted project_fiscal_summary: %', v_rows;
  ELSE RAISE NOTICE '[P8]  skip project_fiscal_summary'; END IF;

  IF v_is_last_fiscal THEN
    RAISE NOTICE '--- Last fiscal: running project-level deletes ---';

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'chat_assistance_session') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_chat_assistance_session (LIKE trd365.chat_assistance_session INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_chat_assistance_session ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format('INSERT INTO %I.bak_main_chat_assistance_session SELECT t.*, $1, $2 FROM trd365.chat_assistance_session t WHERE t.project_rid = $3 AND t.account_rid = $4', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
      DELETE FROM trd365.chat_assistance_session WHERE project_rid = v_project_rid AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P9]  Backed up + deleted chat_assistance_session: %', v_rows;
    ELSE RAISE NOTICE '[P9]  skip chat_assistance_session'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'interactions_summary') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_interactions_summary_project (LIKE trd365.interactions_summary INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_interactions_summary_project ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format('INSERT INTO %I.bak_main_interactions_summary_project SELECT t.*, $1, $2 FROM trd365.interactions_summary t WHERE t.project_rid = $3 AND t.account_rid = $4 AND t.project_fiscal_rid IS NULL', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
      DELETE FROM trd365.interactions_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid AND project_fiscal_rid IS NULL; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P10] Backed up + deleted interactions_summary (project): %', v_rows;
    ELSE RAISE NOTICE '[P10] skip interactions_summary project'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_records') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_rule_engine_records_project (LIKE trd365.rule_engine_records INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_rule_engine_records_project ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_main_rule_engine_records_project SELECT t.*, $1, $2 FROM trd365.rule_engine_records t WHERE t.entity_rid = $3 AND t.entity_type = 'PROJECT' AND t.account_rid = $4$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
      DELETE FROM trd365.rule_engine_records WHERE entity_rid = v_project_rid AND entity_type = 'PROJECT' AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P11] Backed up + deleted rule_engine_records (project): %', v_rows;
    ELSE RAISE NOTICE '[P11] skip rule_engine_records project'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'rule_engine_notification_records') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_rule_engine_notification_project (LIKE trd365.rule_engine_notification_records INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_rule_engine_notification_project ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_main_rule_engine_notification_project SELECT t.*, $1, $2 FROM trd365.rule_engine_notification_records t WHERE t.entity_rid = $3 AND t.entity_type = 'PROJECT' AND t.account_rid = $4$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
      DELETE FROM trd365.rule_engine_notification_records WHERE entity_rid = v_project_rid AND entity_type = 'PROJECT' AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P12] Backed up + deleted rule_engine_notification_records (project): %', v_rows;
    ELSE RAISE NOTICE '[P12] skip rule_engine_notification_records project'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'control_center_execution') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_control_center_execution_project (LIKE trd365.control_center_execution INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_control_center_execution_project ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      BEGIN
        EXECUTE format('ALTER TABLE %I.bak_main_control_center_execution_project ALTER COLUMN duration_ms DROP EXPRESSION IF EXISTS', v_backup_schema);
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
      EXECUTE format('INSERT INTO %I.bak_main_control_center_execution_project SELECT t.*, $1, $2 FROM trd365.control_center_execution t WHERE t.reference_rid = $3 AND t.account_rid = $4', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
      DELETE FROM trd365.control_center_execution WHERE reference_rid = v_project_rid AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P13] Backed up + deleted control_center_execution (project): %', v_rows;
    ELSE RAISE NOTICE '[P13] skip control_center_execution project'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'user_group_entity_access') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_user_group_entity_access_project (LIKE trd365.user_group_entity_access INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_user_group_entity_access_project ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_main_user_group_entity_access_project SELECT t.*, $1, $2 FROM trd365.user_group_entity_access t WHERE t.entity_type = 'PROJECT' AND t.entity_rid = $3$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid;
      DELETE FROM trd365.user_group_entity_access WHERE entity_type = 'PROJECT' AND entity_rid = v_project_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P18] Backed up + deleted user_group_entity_access (project): %', v_rows;
    ELSE RAISE NOTICE '[P18] skip user_group_entity_access project'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_summary') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_project_summary (LIKE trd365.project_summary INCLUDING ALL)', v_backup_schema);
      EXECUTE format('ALTER TABLE %I.bak_main_project_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format('INSERT INTO %I.bak_main_project_summary SELECT t.*, $1, $2 FROM trd365.project_summary t WHERE t.project_rid = $3 AND t.account_rid = $4', v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
      DELETE FROM trd365.project_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P19] Backed up + deleted project_summary: %', v_rows;
    ELSE RAISE NOTICE '[P19] skip project_summary'; END IF;

  ELSE
    RAISE NOTICE '--- Other fiscals remain: recomputing project_summary ---';
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'project_summary') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      UPDATE trd365.project_summary SET
        total_cost          = (SELECT COALESCE(SUM(total_cost_prj),          0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_effort        = (SELECT COALESCE(SUM(total_effort_prj),        0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_fte           = (SELECT COALESCE(SUM(total_fte_prj),           0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_subcon        = (SELECT COALESCE(SUM(total_subcon_prj),        0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_nonlabor      = (SELECT COALESCE(SUM(total_nonlabor_prj),      0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_cost_fte      = (SELECT COALESCE(SUM(total_cost_fte_prj),      0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_cost_subcon   = (SELECT COALESCE(SUM(total_cost_subcon_prj),   0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        total_cost_nonlabor = (SELECT COALESCE(SUM(total_cost_nonlabor_prj), 0) FROM trd365.project_fiscal_summary WHERE project_rid = v_project_rid AND account_rid = v_account_rid),
        modified_datetime   = NOW()
      WHERE project_rid = v_project_rid AND account_rid = v_account_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P9b] Recomputed project_summary: %', v_rows;
    END IF;
  END IF;

  -- attachment_summary / notes_summary / meeting_summary / task_summary are
  -- scoped by project_fiscal_rid as well as project_rid (some rows have
  -- attach_to = project_fiscal_id despite attachment_level = 'project' —
  -- mislabeled/legacy data shape), so unlike project_summary above these
  -- must run on EVERY fiscal deletion, not just the last one. Matched by
  -- attach_to IN (project_rid, project_fiscal_id), not also filtered on
  -- attachment_level, so both correctly-labeled and mislabeled rows are
  -- always caught — by both the delete here and the Section 1 pre-count /
  -- Section 5 post-count.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'attachment_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_attachment_summary (LIKE trd365.attachment_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_attachment_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_attachment_summary SELECT t.*, $1, $2 FROM trd365.attachment_summary t WHERE t.attach_to IN ($3, $2) AND t.account_rid = $4$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
    DELETE FROM trd365.attachment_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P14] Backed up + deleted attachment_summary: %', v_rows;
  ELSE RAISE NOTICE '[P14] skip attachment_summary'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'notes_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_notes_summary (LIKE trd365.notes_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_notes_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_notes_summary SELECT t.*, $1, $2 FROM trd365.notes_summary t WHERE t.attach_to IN ($3, $2) AND t.account_rid = $4$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
    DELETE FROM trd365.notes_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P15] Backed up + deleted notes_summary: %', v_rows;
  ELSE RAISE NOTICE '[P15] skip notes_summary'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'meeting_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_meeting_summary (LIKE trd365.meeting_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_meeting_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_meeting_summary SELECT t.*, $1, $2 FROM trd365.meeting_summary t WHERE t.attach_to IN ($3, $2) AND t.account_rid = $4$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
    DELETE FROM trd365.meeting_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P16] Backed up + deleted meeting_summary: %', v_rows;
  ELSE RAISE NOTICE '[P16] skip meeting_summary'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'task_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_main_task_summary (LIKE trd365.task_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_main_task_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_main_task_summary SELECT t.*, $1, $2 FROM trd365.task_summary t WHERE t.attach_to IN ($3, $2) AND t.account_rid = $4$sql$, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_project_rid, v_account_rid;
    DELETE FROM trd365.task_summary WHERE attach_to IN (v_project_rid, v_project_fiscal_id) AND account_rid = v_account_rid; GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P17] Backed up + deleted task_summary: %', v_rows;
  ELSE RAISE NOTICE '[P17] skip task_summary'; END IF;

  -- Recalculate account_fiscal_summary
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'account_fiscal_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    UPDATE trd365.account_fiscal_summary SET
      total_projects      = (SELECT COUNT(DISTINCT project_code)         FROM trd365.project_fiscal_summary WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year),
      total_project_hours = (SELECT COALESCE(SUM(total_effort_prj),  0)  FROM trd365.project_fiscal_summary WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year),
      total_project_cost  = (SELECT COALESCE(SUM(total_cost_prj),    0)  FROM trd365.project_fiscal_summary WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year),
      total_fte           = (SELECT COALESCE(SUM(total_fte_prj),     0)  FROM trd365.project_fiscal_summary WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year),
      total_subcon        = (SELECT COALESCE(SUM(total_subcon_prj),  0)  FROM trd365.project_fiscal_summary WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year),
      total_nonlabor      = (SELECT COALESCE(SUM(total_nonlabor_prj),0)  FROM trd365.project_fiscal_summary WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year),
      modified_datetime   = NOW()
    WHERE account_rid = v_account_rid AND fiscal_year = v_fiscal_year;
    GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P20] Recomputed account_fiscal_summary: %', v_rows;
  END IF;

  -- Recalculate account top-level aggregates
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'trd365' AND table_name = 'account') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    UPDATE trd365.account SET
      total_projects      = (SELECT COUNT(*)                               FROM trd365.project_summary        WHERE account_rid = v_account_rid),
      total_project_cost  = (SELECT COALESCE(SUM(total_project_cost),  0)  FROM trd365.account_fiscal_summary WHERE account_rid = v_account_rid),
      total_project_hours = (SELECT COALESCE(SUM(total_project_hours), 0)  FROM trd365.account_fiscal_summary WHERE account_rid = v_account_rid)
    WHERE rid = v_account_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT; RAISE NOTICE '[P21] Recomputed account aggregates: %', v_rows;
  END IF;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 3 — MAIN DB DELETE COMPLETE';
  RAISE NOTICE 'Backup schema: %.project_main_inputs / %.project_main_pre (run_at = %)', v_backup_schema, v_backup_schema, v_run_at;
  RAISE NOTICE 'Next: run SECTION 4 (ORG DB diff) then SECTION 5 (MAIN DB diff).';
  RAISE NOTICE '==============================================================';

EXCEPTION
  WHEN OTHERS THEN
    RAISE EXCEPTION 'SECTION 3 aborted (rolled back). SQLSTATE=%, ERROR=%', SQLSTATE, SQLERRM;
END;
$$;


-- =============================================================================
