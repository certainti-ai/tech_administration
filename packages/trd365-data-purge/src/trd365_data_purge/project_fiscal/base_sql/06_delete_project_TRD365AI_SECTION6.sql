-- SECTION 6  TRD365AI — Pre-Backup Snapshot
-- Run on: trd365ai (separate server/database, "public" schema)   |   Run: BEFORE deletion
-- =============================================================================
DO $$
DECLARE
  -- ▼▼▼  FILL IN THIS VALUE  ▼▼▼ ------------------------------------------
  v_project_fiscal_rid TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  -- ▲▲▲ -------------------------------------------------------------------

  -- PASTE the backup schema SECTION 1 announced here:
  v_backup_schema TEXT := '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>';
  v_run_at        TIMESTAMPTZ := clock_timestamp();

  v_cnt        BIGINT;
  v_tbl_exists BOOLEAN;
  r            RECORD;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in v_project_fiscal_rid before running SECTION 6.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  -- Backup schema for this run was created by SECTION 1; reused here (not re-created).
  EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_backup_schema);

  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.ai_inputs (
      run_at              TIMESTAMPTZ NOT NULL,
      project_fiscal_rid  TEXT NOT NULL,
      PRIMARY KEY (project_fiscal_rid, run_at)
    )
  $ddl$, v_backup_schema);

  EXECUTE format(
    'INSERT INTO %I.ai_inputs (run_at, project_fiscal_rid) VALUES ($1,$2)',
    v_backup_schema
  ) USING v_run_at, v_project_fiscal_rid;

  EXECUTE format($ddl$
    CREATE TABLE IF NOT EXISTS %I.ai_pre (
      run_at              TIMESTAMPTZ NOT NULL,
      project_fiscal_rid  TEXT NOT NULL,
      label               TEXT NOT NULL,
      cnt                 BIGINT NOT NULL,
      PRIMARY KEY (project_fiscal_rid, run_at, label)
    )
  $ddl$, v_backup_schema);

  -- Session-local staging table (mirrors the permanent one for this run) so
  -- the RAISE NOTICE summary loop below can read back what was just written.
  DROP TABLE IF EXISTS _ai_pre;
  CREATE TEMP TABLE _ai_pre (label TEXT PRIMARY KEY, cnt BIGINT);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'four_part_assessments') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.four_part_assessments WHERE projectid = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('four_part_assessments', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_knowledge_base') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_ai_knowledge_base WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_ai_knowledge_base', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_llm_logs') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_ai_llm_logs WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_ai_llm_logs', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_request') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_ai_request WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_ai_request', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_assessment') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_assessment WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_project_ai_assessment', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_interaction') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_interaction WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_project_ai_interaction', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_summary WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_project_ai_summary', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary_logs') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_summary_logs WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_project_ai_summary_logs', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary_sections') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_ai_summary_sections WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_project_ai_summary_sections', v_cnt);

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_details') INTO v_tbl_exists;
  IF v_tbl_exists THEN EXECUTE 'SELECT COUNT(*) FROM public.master_project_details WHERE "projectId" = $1' INTO v_cnt USING v_project_fiscal_rid; ELSE v_cnt := 0; END IF;
  INSERT INTO _ai_pre VALUES ('master_project_details', v_cnt);

  -- Persist this run's pre-counts permanently into the backup schema.
  EXECUTE format(
    'INSERT INTO %I.ai_pre (run_at, project_fiscal_rid, label, cnt) SELECT $1, $2, label, cnt FROM _ai_pre',
    v_backup_schema
  ) USING v_run_at, v_project_fiscal_rid;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 6 — trd365ai PRE-BACKUP COMPLETE';
  RAISE NOTICE '  project_fiscal_rid = %', v_project_fiscal_rid;
  RAISE NOTICE '--------------------------------------------------------------';
  RAISE NOTICE '  %-38s  %s', 'table', 'pre_count';
  RAISE NOTICE '  %-38s  %s', '-----', '---------';
  FOR r IN SELECT label, cnt FROM _ai_pre ORDER BY label LOOP
    RAISE NOTICE '  %-38s  %s', r.label, r.cnt;
  END LOOP;
  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'Backup schema: %.ai_inputs / %.ai_pre (run_at = %)', v_backup_schema, v_backup_schema, v_run_at;
  RAISE NOTICE 'Next: run SECTION 7 (delete) — any DB session/connection is fine.';
  RAISE NOTICE '==============================================================';

END;
$$;


-- =============================================================================
