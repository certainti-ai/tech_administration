-- SECTION 4  ORG DB — Post-Delete Diff
-- Run on: thinkrd365_org   |   Run: AFTER Sections 2 and 3
-- Reads v_backup_schema from a hand-pasted placeholder (the value SECTION 1
-- announced for this run) — no cross-session shared lookup table anymore.
-- =============================================================================
DO $$
DECLARE
  -- ▼▼▼  FILL IN  ▼▼▼ -------------------------------------------------------
  v_lookup_project_fiscal_id TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';  -- same value used in SECTION 1
  -- ▲▲▲ -------------------------------------------------------------------

  -- PASTE the backup schema SECTION 1 announced here:
  v_backup_schema     TEXT := 'backup_release_v5_3_3_trd365_0137_PRJ_2024_20260723_083409';
  v_run_at            TIMESTAMPTZ := clock_timestamp();
  v_pre_run_at        TIMESTAMPTZ;  -- resolved below from this run's pre-snapshot
  v_schema_name       TEXT := 'trd365_01379';
  v_account_rid       TEXT := 'D001-4bf2b0a2-f11c-4941-b075-82e8682a1e20';
  v_project_rid       TEXT := 'D001-a9fc5b2a-8a2d-4895-bd28-817ae0b51f33';
  v_project_fiscal_id TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  v_is_last_fiscal    BOOLEAN := FALSE;

  v_pre  BIGINT; v_post BIGINT; v_scope TEXT; v_label TEXT;
  v_pass INT := 0; v_fail INT := 0; v_skip INT := 0;
  v_tbl_exists BOOLEAN;
  r      RECORD;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in v_lookup_project_fiscal_id before running SECTION 4.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  -- Resolve THIS run's pre-snapshot timestamp from the backup schema (SECTION 1
  -- wrote project_org_pre). Formerly a hand-pasted literal; now looked up so the
  -- diff always compares against the current run's counts.
  EXECUTE format('SELECT max(run_at) FROM %I.project_org_pre WHERE project_fiscal_id = $1', v_backup_schema)
    INTO v_pre_run_at USING v_lookup_project_fiscal_id;
  IF v_pre_run_at IS NULL THEN
    RAISE EXCEPTION 'SECTION 4: no pre-snapshot in %.project_org_pre for % — run SECTION 1 first.',
      v_backup_schema, v_lookup_project_fiscal_id;
  END IF;

  -- Permanent table for this section's post-delete counts.
  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.project_org_post (
      run_at             TIMESTAMPTZ NOT NULL,
      project_fiscal_id  TEXT NOT NULL,
      label              TEXT NOT NULL,
      cnt                BIGINT NOT NULL,
      scope              TEXT NOT NULL,
      PRIMARY KEY (project_fiscal_id, run_at, label)
    )
  $ddl$, v_backup_schema);

  DROP TABLE IF EXISTS _prj_org_post_staging;
  CREATE TEMP TABLE _prj_org_post_staging (label TEXT PRIMARY KEY, cnt BIGINT, scope TEXT);

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 4 — ORG DB POST-DELETE DIFF';
  RAISE NOTICE '  schema = %  |  fiscal = %  |  last_fiscal = %  |  pre_run_at = %',
    v_schema_name, v_project_fiscal_id, v_is_last_fiscal, v_pre_run_at;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  %-42s  %7s  %7s  %6s  %s', 'table', 'pre', 'post', 'diff', 'result';
  RAISE NOTICE '  %-42s  %7s  %7s  %6s  %s', '-----', '---', '----', '----', '------';

  FOR r IN EXECUTE format(
    'SELECT label, cnt AS pre, scope FROM %I.project_org_pre WHERE project_fiscal_id = $1 AND run_at = $2 ORDER BY scope, label',
    v_backup_schema
  ) USING v_lookup_project_fiscal_id, v_pre_run_at LOOP
    v_label := r.label; v_pre := r.pre; v_scope := r.scope;

    CASE v_label
      WHEN 'interactions' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interactions') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.interactions WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'interaction_items' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_items') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_items ii JOIN %I.interactions i ON ii.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'interaction_response_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_response_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_response_history irh JOIN %I.interaction_items ii ON irh.interaction_item_rid = ii.rid JOIN %I.interactions i ON ii.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'interaction_timeline' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_timeline') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_timeline it JOIN %I.interactions i ON it.entity_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'interaction_attachments' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_attachments') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_attachments ia JOIN %I.interactions i ON ia.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'interaction_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.interaction_history WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'interaction_status_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_status_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.interaction_status_history ish JOIN %I.interactions i ON ish.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'otp_entries_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'otp_entries_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.otp_entries_history oeh JOIN %I.interactions i ON oeh.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'otp_entries' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'otp_entries') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.otp_entries oe JOIN %I.interactions i ON oe.interaction_rid = i.rid WHERE i.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'four_part_assessment' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'four_part_assessment') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.four_part_assessment WHERE project_fiscal_rid = $1 AND account_rid = $2', v_schema_name) INTO v_post USING v_project_fiscal_id, v_account_rid; ELSE v_post := 0; END IF;
      WHEN 'project_task' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_task WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_task_timeline' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task_timeline') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_task_timeline ptt JOIN %I.project_task pt ON ptt.entity_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_task_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_task_history pth JOIN %I.project_task pt ON pth.project_task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'task_tags' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_tags') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_tags tt JOIN %I.project_task pt ON tt.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'task_comments' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_comments') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_comments tc JOIN %I.project_task pt ON tc.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'task_collaborators' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_collaborators') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_collaborators tc JOIN %I.project_task pt ON tc.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'task_attachments' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_attachments') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_attachments ta JOIN %I.project_task pt ON ta.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'task_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.task_history th JOIN %I.project_task pt ON th.task_rid = pt.rid WHERE pt.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_resource' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_resource WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_resource_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_fiscal') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_resource_fiscal WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_resource_fiscal_region' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_fiscal_region') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_resource_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_resource_timeline' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_timeline') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_resource_timeline prt JOIN %I.project_resource pr ON prt.entity_rid = pr.rid WHERE pr.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_resource_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.project_resource_history prh JOIN %I.project_resource pr ON prh.project_resource_rid = pr.rid WHERE pr.project_fiscal_rid = $1$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'ai_technical_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_technical_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.ai_technical_summary WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'ai_assessment_audit' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_audit') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.ai_assessment_audit WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'ai_assessment_qre' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_qre') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.ai_assessment_qre WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'ai_assessment_error' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_error') INTO v_tbl_exists;
        IF v_tbl_exists THEN
          EXECUTE format($s$SELECT COUNT(*) FROM %I.ai_assessment_error WHERE account_rid = $1 AND project_rid IN (SELECT project_rid FROM %I.project_fiscal WHERE rid = $2)$s$, v_schema_name, v_schema_name) INTO v_post USING v_account_rid, v_project_fiscal_id;
        ELSE
          v_post := 0;
        END IF;
      WHEN 'autosend_interaction_audit' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'autosend_interaction_audit') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.autosend_interaction_audit WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_qre_adjustment_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_qre_adjustment_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_qre_adjustment_history WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_fiscal_region' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_fiscal_region') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_fiscal_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_fiscal_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_fiscal_history WHERE project_fiscal_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_history_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_history WHERE project_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_timeline_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline WHERE entity_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_timeline_old_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline_old') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline_old WHERE entity_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'account_timeline_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'account_timeline') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.account_timeline WHERE entity_rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_fiscal' THEN
        -- project_fiscal row itself; confirmed to exist during Section 1.
        EXECUTE format('SELECT COUNT(*) FROM %I.project_fiscal WHERE rid = $1', v_schema_name) INTO v_post USING v_project_fiscal_id;
      WHEN 'activity_attachments' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activity_attachments') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.activity_attachments aa JOIN %I.activities a ON aa.activity_rid = a.rid WHERE a.attach_to IN ($1, $2)$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_rid, v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'activity_history' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activity_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.activity_history ah JOIN %I.activities a ON ah.activity_rid = a.rid WHERE a.attach_to IN ($1, $2)$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_rid, v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'meeting_summary_org' THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'meeting_summary') THEN
          EXECUTE format($s$SELECT COUNT(*) FROM %I.meeting_summary ms JOIN %I.activities a ON ms.activity_rid = a.rid WHERE a.attach_to IN ($1, $2)$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_rid, v_project_fiscal_id;
        ELSE
          v_post := 0;
        END IF;
      WHEN 'activities' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activities') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.activities WHERE attach_to IN ($1, $2)$s$, v_schema_name) INTO v_post USING v_project_rid, v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'notes_timeline' THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'notes') THEN
          EXECUTE format($s$SELECT COUNT(*) FROM %I.notes_timeline WHERE attach_to IN (SELECT rid FROM %I.notes WHERE attach_to IN ($1, $2))$s$, v_schema_name, v_schema_name) INTO v_post USING v_project_rid, v_project_fiscal_id;
        ELSE
          v_post := 0;
        END IF;
      WHEN 'notes' THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'notes') THEN
          EXECUTE format($s$SELECT COUNT(*) FROM %I.notes WHERE attach_to IN ($1, $2)$s$, v_schema_name) INTO v_post USING v_project_rid, v_project_fiscal_id;
        ELSE
          v_post := 0;
        END IF;
      WHEN 'attachments_fiscal' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'attachments') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format($s$SELECT COUNT(*) FROM %I.attachments WHERE attach_to = $1$s$, v_schema_name) INTO v_post USING v_project_fiscal_id; ELSE v_post := 0; END IF;
      WHEN 'project_history_parent' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_history') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_history WHERE project_rid = $1', v_schema_name) INTO v_post USING v_project_rid; ELSE v_post := 0; END IF;
      WHEN 'project_timeline_parent' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline WHERE entity_rid = $1', v_schema_name) INTO v_post USING v_project_rid; ELSE v_post := 0; END IF;
      WHEN 'project_timeline_old_parent' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline_old') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.project_timeline_old WHERE entity_rid = $1', v_schema_name) INTO v_post USING v_project_rid; ELSE v_post := 0; END IF;
      WHEN 'key_contact_details' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'key_contact_details') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE format('SELECT COUNT(*) FROM %I.key_contact_details WHERE entity_rid = $1', v_schema_name) INTO v_post USING v_project_rid; ELSE v_post := 0; END IF;
      WHEN 'project_parent' THEN
        -- project row itself; confirmed to exist during Section 1.
        EXECUTE format('SELECT COUNT(*) FROM %I.project WHERE rid = $1', v_schema_name) INTO v_post USING v_project_rid;
      ELSE v_post := -1;
    END CASE;

    INSERT INTO _prj_org_post_staging VALUES (v_label, v_post, v_scope);

    IF v_scope = 'project' AND NOT v_is_last_fiscal THEN
      v_skip := v_skip + 1;
      RAISE NOTICE '  %-42s  %7s  %7s  %6s  SKIP', v_label, v_pre, v_post, v_post - v_pre;
    ELSIF v_post = 0 THEN
      v_pass := v_pass + 1;
      RAISE NOTICE '  %-42s  %7s  %7s  %6s  PASS', v_label, v_pre, v_post, 0 - v_pre;
    ELSE
      v_fail := v_fail + 1;
      RAISE WARNING '  %-42s  %7s  %7s  %6s  FAIL ← rows still exist', v_label, v_pre, v_post, v_post - v_pre;
    END IF;
  END LOOP;

  -- Persist this run's post-counts permanently into the backup schema.
  EXECUTE format(
    'INSERT INTO %I.project_org_post (run_at, project_fiscal_id, label, cnt, scope) SELECT $1, $2, label, cnt, scope FROM _prj_org_post_staging',
    v_backup_schema
  ) USING v_run_at, v_lookup_project_fiscal_id;

  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  PASS: %   FAIL: %   SKIP (not last fiscal): %', v_pass, v_fail, v_skip;
  IF v_fail > 0 THEN
    RAISE EXCEPTION 'SECTION 4: % row(s) failed diff — investigate before sign-off.', v_fail;
  ELSE
    RAISE NOTICE 'ORG DB diff clean.';
    RAISE NOTICE 'SECTION 4 — ORG DB POST-DELETE DIFF COMPLETE';
  END IF;
  RAISE NOTICE 'Backup schema: %.project_org_post (run_at = %)', v_backup_schema, v_run_at;
  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'Next: switch to MAIN DB and run SECTION 5.';
  RAISE NOTICE '==============================================================';
END;
$$;


-- =============================================================================
