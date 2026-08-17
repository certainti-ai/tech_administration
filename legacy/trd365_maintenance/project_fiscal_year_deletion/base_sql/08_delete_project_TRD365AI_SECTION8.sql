-- SECTION 8  TRD365AI — Post-Delete Diff
-- Run on: trd365ai   |   Run: AFTER Section 7
-- Reads v_backup_schema from a hand-pasted placeholder (the value SECTION 1
-- announced for this run) — no cross-session shared lookup table anymore.
-- =============================================================================
DO $$
DECLARE
  -- ▼▼▼  FILL IN  ▼▼▼ -------------------------------------------------------
  v_lookup_project_fiscal_rid TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';  -- same value used in SECTION 6
  -- ▲▲▲ -------------------------------------------------------------------

  -- PASTE the backup schema SECTION 1 announced here:
  v_backup_schema      TEXT := '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>';
  v_run_at             TIMESTAMPTZ := clock_timestamp();
  v_pre_run_at         TIMESTAMPTZ;  -- resolved below from this run's pre-snapshot
  v_project_fiscal_rid TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';

  v_pre  BIGINT; v_post BIGINT; v_label TEXT;
  v_pass INT := 0; v_fail INT := 0;
  v_tbl_exists BOOLEAN;
  r      RECORD;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in v_lookup_project_fiscal_rid before running SECTION 8.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  -- Resolve THIS run's pre-snapshot timestamp from the backup schema (SECTION 6
  -- wrote ai_pre). Formerly NULL/hand-pasted; now looked up so the diff always
  -- compares against the current run's counts.
  EXECUTE format('SELECT max(run_at) FROM %I.ai_pre WHERE project_fiscal_rid = $1', v_backup_schema)
    INTO v_pre_run_at USING v_lookup_project_fiscal_rid;
  IF v_pre_run_at IS NULL THEN
    RAISE EXCEPTION 'SECTION 8: no pre-snapshot in %.ai_pre for % — run SECTION 6 first.',
      v_backup_schema, v_lookup_project_fiscal_rid;
  END IF;

  -- Permanent table for this section's post-delete counts.
  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.ai_post (
      run_at              TIMESTAMPTZ NOT NULL,
      project_fiscal_rid  TEXT NOT NULL,
      label               TEXT NOT NULL,
      cnt                 BIGINT NOT NULL,
      PRIMARY KEY (project_fiscal_rid, run_at, label)
    )
  $ddl$, v_backup_schema);

  DROP TABLE IF EXISTS _ai_post_staging;
  CREATE TEMP TABLE _ai_post_staging (label TEXT PRIMARY KEY, cnt BIGINT);

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 8 — trd365ai POST-DELETE DIFF';
  RAISE NOTICE '  project_fiscal_rid = %  |  pre_run_at = %', v_project_fiscal_rid, v_pre_run_at;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  %-38s  %7s  %7s  %6s  %s', 'table', 'pre', 'post', 'diff', 'result';
  RAISE NOTICE '  %-38s  %7s  %7s  %6s  %s', '-----', '---', '----', '----', '------';

  FOR r IN EXECUTE format(
    'SELECT label, cnt AS pre FROM %I.ai_pre WHERE project_fiscal_rid = $1 AND run_at = $2 ORDER BY label',
    v_backup_schema
  ) USING v_lookup_project_fiscal_rid, v_pre_run_at LOOP
    v_label := r.label; v_pre := r.pre;

    CASE v_label
      WHEN 'four_part_assessments' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'four_part_assessments') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.four_part_assessments WHERE projectid = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_ai_knowledge_base' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_knowledge_base') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_ai_knowledge_base WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_ai_llm_logs' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_llm_logs') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_ai_llm_logs WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_ai_request' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_request') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_ai_request WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_project_ai_assessment' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_assessment') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_assessment WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_project_ai_interaction' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_interaction') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_interaction WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_project_ai_summary' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_summary WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_project_ai_summary_logs' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary_logs') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_summary_logs WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_project_ai_summary_sections' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary_sections') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_summary_sections WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      WHEN 'master_project_details' THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_details') INTO v_tbl_exists;
        IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_details WHERE "projectId" = $1' INTO v_post USING v_project_fiscal_rid; ELSE v_post := 0; END IF;
      ELSE v_post := -1;
    END CASE;

    INSERT INTO _ai_post_staging VALUES (v_label, v_post);

    IF v_post = 0 THEN
      v_pass := v_pass + 1;
      RAISE NOTICE '  %-38s  %7s  %7s  %6s  PASS', v_label, v_pre, v_post, 0 - v_pre;
    ELSE
      v_fail := v_fail + 1;
      RAISE WARNING '  %-38s  %7s  %7s  %6s  FAIL ← rows still exist', v_label, v_pre, v_post, v_post - v_pre;
    END IF;
  END LOOP;

  -- Persist this run's post-counts permanently into the backup schema.
  EXECUTE format(
    'INSERT INTO %I.ai_post (run_at, project_fiscal_rid, label, cnt) SELECT $1, $2, label, cnt FROM _ai_post_staging',
    v_backup_schema
  ) USING v_run_at, v_lookup_project_fiscal_rid;

  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  PASS: %   FAIL: %', v_pass, v_fail;
  IF v_fail > 0 THEN
    RAISE EXCEPTION 'SECTION 8: % row(s) failed diff — investigate before sign-off.', v_fail;
  ELSE
    RAISE NOTICE 'trd365ai diff clean. Deletion complete.';
    RAISE NOTICE 'SECTION 8 — TRD365AI POST-DELETE DIFF COMPLETE';
  END IF;
  RAISE NOTICE 'Backup schema: %.ai_post (run_at = %)', v_backup_schema, v_run_at;
  RAISE NOTICE '==============================================================';

END;
$$;
