-- SECTION 1  ORG DB — Pre-Backup Snapshot
-- Run on: thinkrd365_org   |   Run: BEFORE deletion
-- =============================================================================
DO $$
DECLARE
  -- ▼▼▼  FILL IN THESE VALUES  ▼▼▼ ------------------------------------------
  v_schema_name       TEXT    := 'trd365_01379';    -- e.g. trd365_00942
  v_account_rid       TEXT    := 'D001-4bf2b0a2-f11c-4941-b075-82e8682a1e20';
  v_project_rid       TEXT    := 'D001-a9fc5b2a-8a2d-4895-bd28-817ae0b51f33';
  v_project_fiscal_id TEXT    := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  v_is_last_fiscal    BOOLEAN := FALSE;  -- TRUE if this is the only remaining fiscal
  -- ▲▲▲ -------------------------------------------------------------------

  v_backup_schema TEXT;
  v_run_at        TIMESTAMPTZ := clock_timestamp();

  v_cnt BIGINT;
  v_tbl_exists BOOLEAN;
  r     RECORD;
BEGIN

  -- One backup schema PER RUN (never reused). The name is run-scoped — a single
  -- timestamped schema for the whole execution, NOT per account/project — so
  -- every project deleted in the same run backs up into it. Postgres identifiers
  -- are capped at 63 chars (NAMEDATALEN); this name stays well under that. The
  -- run's inputs (schema_name/account_rid/project_rid/project_fiscal_id) are
  -- recorded in the project_org_inputs table below, so identifying details are
  -- preserved there rather than in the schema name.
  -- NOTE: when driven by run.py, this whole assignment is replaced in memory
  -- with the single execution-wide schema name the runner injects into every
  -- section — so file and runner produce the same run-scoped shape either way.
  v_backup_schema := 'backup_release_v5_3_3_run_'
    || to_char(clock_timestamp(), 'YYYYMMDD_HH24MISS');

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in input values before running SECTION 1.';
  END IF;

  -- Brand-new backup schema for this run only (never reused).
  EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_backup_schema);

  -- Persist this run's inputs for record-keeping (SECTION 2/4 no longer read
  -- them back — v_backup_schema is now hand-carried between sections).
  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.project_org_inputs (
      run_at             TIMESTAMPTZ NOT NULL,
      schema_name        TEXT NOT NULL,
      account_rid        TEXT NOT NULL,
      project_rid        TEXT NOT NULL,
      project_fiscal_id  TEXT NOT NULL,
      is_last_fiscal     BOOLEAN NOT NULL,
      PRIMARY KEY (project_fiscal_id, run_at)
    )
  $ddl$, v_backup_schema);

  EXECUTE format(
    'INSERT INTO %I.project_org_inputs (run_at, schema_name, account_rid, project_rid, project_fiscal_id, is_last_fiscal) VALUES ($1,$2,$3,$4,$5,$6)',
    v_backup_schema
  ) USING v_run_at, v_schema_name, v_account_rid, v_project_rid, v_project_fiscal_id, v_is_last_fiscal;

  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.project_org_pre (
      run_at             TIMESTAMPTZ NOT NULL,
      project_fiscal_id  TEXT NOT NULL,
      label              TEXT NOT NULL,
      cnt                BIGINT NOT NULL,
      scope              TEXT NOT NULL,
      PRIMARY KEY (project_fiscal_id, run_at, label)
    )
  $ddl$, v_backup_schema);

  -- Session-local staging table (mirrors the permanent one for this run) so
  -- the RAISE NOTICE summary loop below can read back what was just written.
  DROP TABLE IF EXISTS _prj_org_pre;
  CREATE TEMP TABLE _prj_org_pre (label TEXT PRIMARY KEY, cnt BIGINT, scope TEXT);
  -- scope: 'fiscal' = always deleted | 'project' = last-fiscal only

  -- Interactions
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interactions') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.interactions WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interactions', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_items') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_items ii JOIN %I.interactions i ON ii.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interaction_items', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_response_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_response_history irh JOIN %I.interaction_items ii ON irh.interaction_item_rid = ii.rid JOIN %I.interactions i ON ii.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interaction_response_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_timeline it JOIN %I.interactions i ON it.entity_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interaction_timeline', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_attachments ia JOIN %I.interactions i ON ia.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interaction_attachments', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.interaction_history WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interaction_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_status_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_status_history ish JOIN %I.interactions i ON ish.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('interaction_status_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'otp_entries_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.otp_entries_history oeh JOIN %I.interactions i ON oeh.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('otp_entries_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'otp_entries') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.otp_entries oe JOIN %I.interactions i ON oe.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('otp_entries', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'four_part_assessment') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.four_part_assessment WHERE project_fiscal_rid = $1 AND account_rid = $2', v_schema_name) INTO v_cnt USING v_project_fiscal_id, v_account_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('four_part_assessment', v_cnt, 'fiscal');

  -- Tasks
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_task WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_task', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_task_timeline ptt JOIN %I.project_task pt ON ptt.entity_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_task_timeline', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_task_history pth JOIN %I.project_task pt ON pth.project_task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_task_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_tags') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_tags tt JOIN %I.project_task pt ON tt.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('task_tags', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_comments') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_comments tc JOIN %I.project_task pt ON tc.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('task_comments', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_collaborators') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_collaborators tc JOIN %I.project_task pt ON tc.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('task_collaborators', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_attachments ta JOIN %I.project_task pt ON ta.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('task_attachments', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_history th JOIN %I.project_task pt ON th.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('task_history', v_cnt, 'fiscal');

  -- Resources
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_resource WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_resource', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_fiscal') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_resource_fiscal WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_resource_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_fiscal_region') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_resource_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_resource_fiscal_region', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_resource_timeline prt JOIN %I.project_resource pr ON prt.entity_rid = pr.rid WHERE pr.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_resource_timeline', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_resource_history prh JOIN %I.project_resource pr ON prh.project_resource_rid = pr.rid WHERE pr.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_resource_history', v_cnt, 'fiscal');

  -- AI / assessment
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_technical_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.ai_technical_summary WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('ai_technical_summary', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_audit') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.ai_assessment_audit WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('ai_assessment_audit', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_qre') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.ai_assessment_qre WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('ai_assessment_qre', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_error') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($s$SELECT COUNT(*) FROM %I.ai_assessment_error WHERE account_rid = $1 AND project_rid IN (SELECT project_rid FROM %I.project_fiscal WHERE rid = $2)$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_account_rid, v_project_fiscal_id;
  ELSE
    v_cnt := 0;
  END IF;
  INSERT INTO _prj_org_pre VALUES ('ai_assessment_error', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'autosend_interaction_audit') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.autosend_interaction_audit WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('autosend_interaction_audit', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_qre_adjustment_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_qre_adjustment_history WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_qre_adjustment_history', v_cnt, 'fiscal');

  -- Fiscal row
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_fiscal_region') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_fiscal_region', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_fiscal_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_fiscal_history WHERE project_fiscal_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_fiscal_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_history WHERE project_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_history_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline WHERE entity_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_timeline_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline_old') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline_old WHERE entity_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_timeline_old_fiscal', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'account_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.account_timeline WHERE entity_rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('account_timeline_fiscal', v_cnt, 'fiscal');

  -- project_fiscal is the terminal/anchor row for Step 1's identification —
  -- always expected to exist since Section 1's own EXCEPTION guard above
  -- already confirmed v_project_fiscal_id resolves to a real row.
  EXECUTE format('SELECT COUNT(*) FROM %I.project_fiscal WHERE rid = $1', v_schema_name) INTO v_cnt USING v_project_fiscal_id;
  INSERT INTO _prj_org_pre VALUES ('project_fiscal', v_cnt, 'fiscal');

  -- Activities / notes / attachments — matched by attach_to IN (project_rid,
  -- project_fiscal_id), not also filtered on attachment_level, since some
  -- rows have attach_to = project_fiscal_id despite attachment_level =
  -- 'project' (mislabeled/legacy data shape). See SECTION 2 delete comment.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activity_attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.activity_attachments aa JOIN %I.activities a ON aa.activity_rid = a.rid WHERE a.attach_to IN ($1, $2)$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_rid, v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('activity_attachments', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activity_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.activity_history ah JOIN %I.activities a ON ah.activity_rid = a.rid WHERE a.attach_to IN ($1, $2)$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_rid, v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('activity_history', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'meeting_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($s$SELECT COUNT(*) FROM %I.meeting_summary ms JOIN %I.activities a ON ms.activity_rid = a.rid WHERE a.attach_to IN ($1, $2)$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_rid, v_project_fiscal_id;
  ELSE
    v_cnt := 0;
  END IF;
  INSERT INTO _prj_org_pre VALUES ('meeting_summary_org', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activities') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.activities WHERE attach_to IN ($1, $2)$s$, v_schema_name) INTO v_cnt USING v_project_rid, v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('activities', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'notes') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($s$SELECT COUNT(*) FROM %I.notes_timeline WHERE attach_to IN (SELECT rid FROM %I.notes WHERE attach_to IN ($1, $2))$s$, v_schema_name, v_schema_name) INTO v_cnt USING v_project_rid, v_project_fiscal_id;
  ELSE
    v_cnt := 0;
  END IF;
  INSERT INTO _prj_org_pre VALUES ('notes_timeline', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'notes') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($s$SELECT COUNT(*) FROM %I.notes WHERE attach_to IN ($1, $2)$s$, v_schema_name) INTO v_cnt USING v_project_rid, v_project_fiscal_id;
  ELSE
    v_cnt := 0;
  END IF;
  INSERT INTO _prj_org_pre VALUES ('notes', v_cnt, 'fiscal');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'attachments') INTO v_tbl_exists;
  -- Matched by attach_to alone (not also attachment_level) — some rows have
  -- attach_to = project_fiscal_id but a mismatched/stale attachment_level
  -- value, which would otherwise silently escape this count and the delete.
  IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.attachments WHERE attach_to = $1$s$, v_schema_name) INTO v_cnt USING v_project_fiscal_id; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('attachments_fiscal', v_cnt, 'fiscal');

  -- Parent project (last fiscal only)
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_history WHERE project_rid = $1', v_schema_name) INTO v_cnt USING v_project_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_history_parent', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline WHERE entity_rid = $1', v_schema_name) INTO v_cnt USING v_project_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_timeline_parent', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline_old') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline_old WHERE entity_rid = $1', v_schema_name) INTO v_cnt USING v_project_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('project_timeline_old_parent', v_cnt, 'project');

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'key_contact_details') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.key_contact_details WHERE entity_rid = $1', v_schema_name) INTO v_cnt USING v_project_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _prj_org_pre VALUES ('key_contact_details', v_cnt, 'project');

  -- project is the terminal/anchor row for the parent project, expected to
  -- exist whenever v_project_rid resolves (already confirmed via Section 1).
  EXECUTE format('SELECT COUNT(*) FROM %I.project WHERE rid = $1', v_schema_name) INTO v_cnt USING v_project_rid;
  INSERT INTO _prj_org_pre VALUES ('project_parent', v_cnt, 'project');

  -- Persist this run's pre-counts permanently into the backup schema.
  EXECUTE format(
    'INSERT INTO %I.project_org_pre (run_at, project_fiscal_id, label, cnt, scope) SELECT $1, $2, label, cnt, scope FROM _prj_org_pre',
    v_backup_schema
  ) USING v_run_at, v_project_fiscal_id;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 1 — ORG DB PRE-BACKUP COMPLETE';
  RAISE NOTICE '  schema = %  |  fiscal = %  |  last_fiscal = %',
    v_schema_name, v_project_fiscal_id, v_is_last_fiscal;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  %-42s  %8s  %s', 'table', 'pre_count', 'scope';
  RAISE NOTICE '  %-42s  %8s  %s', '-----', '---------', '-----';
  FOR r IN SELECT label, cnt, scope FROM _prj_org_pre ORDER BY scope, label LOOP
    RAISE NOTICE '  %-42s  %8s  %s', r.label, r.cnt,
      CASE r.scope WHEN 'fiscal' THEN '(always deleted)' ELSE '(last fiscal only)' END;
  END LOOP;
  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'Backup schema: %.project_org_inputs / %.project_org_pre (run_at = %)', v_backup_schema, v_backup_schema, v_run_at;
  RAISE NOTICE '=== IMPORTANT: backup schema for this run = % ===', v_backup_schema;
  RAISE NOTICE 'Copy this exact value into v_backup_schema in SECTION 2 (and 3/4/5/6/7/8) before running them.';
  RAISE NOTICE 'Next: run SECTION 2 (ORG DB delete) — any DB session/connection is fine.';
  RAISE NOTICE '==============================================================';

END;
$$;


-- =============================================================================
