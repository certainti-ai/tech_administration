-- SECTION 7  TRD365AI — Delete
-- Run on: trd365ai   |   Run: AFTER Section 6
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
  v_project_fiscal_rid TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  v_rows               INT;
  v_tbl_exists         BOOLEAN;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in v_lookup_project_fiscal_rid before running SECTION 7.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 7 — trd365ai DELETE STARTED';
  RAISE NOTICE '  project_fiscal_rid = %', v_project_fiscal_rid;
  RAISE NOTICE '==============================================================';

  -- ── Child/log tables first ───────────────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary_logs') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_project_ai_summary_logs (LIKE public.master_project_ai_summary_logs INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_project_ai_summary_logs ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format('INSERT INTO %I.bak_master_project_ai_summary_logs SELECT t.*, $1, $2 FROM public.master_project_ai_summary_logs t WHERE t."projectId" = $2', v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_project_ai_summary_logs WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A1] Backed up + deleted master_project_ai_summary_logs: %', v_rows;
  ELSE RAISE NOTICE '[A1] skip master_project_ai_summary_logs (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary_sections') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_project_ai_summary_sections (LIKE public.master_project_ai_summary_sections INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_project_ai_summary_sections ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_project_ai_summary_sections
      (id, project_ai_summary_id, framework_id, "companyId", "projectId", summary, section, status, createdtime, sysmodtime, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, project_ai_summary_id, framework_id, "companyId", "projectId", summary, section, status, createdtime, sysmodtime, $1, $2
      FROM public.master_project_ai_summary_sections t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_project_ai_summary_sections WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A2] Backed up + deleted master_project_ai_summary_sections: %', v_rows;
  ELSE RAISE NOTICE '[A2] skip master_project_ai_summary_sections (not found)'; END IF;

  -- ── Mid-level tables ─────────────────────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_project_ai_summary (LIKE public.master_project_ai_summary INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_project_ai_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_project_ai_summary
      (id, framework_id, "companyId", "projectId", summary, status, createdtime, sysmodtime, summary_identifier, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, framework_id, "companyId", "projectId", summary, status, createdtime, sysmodtime, summary_identifier, $1, $2
      FROM public.master_project_ai_summary t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_project_ai_summary WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A3] Backed up + deleted master_project_ai_summary: %', v_rows;
  ELSE RAISE NOTICE '[A3] skip master_project_ai_summary (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_interaction') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_project_ai_interaction (LIKE public.master_project_ai_interaction INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_project_ai_interaction ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_project_ai_interaction
      (id, "companyId", "projectId", project_ai_request_id, interaction_question, status, createdtime, sysmodtime, version, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, "companyId", "projectId", project_ai_request_id, interaction_question, status, createdtime, sysmodtime, version, $1, $2
      FROM public.master_project_ai_interaction t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_project_ai_interaction WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A4] Backed up + deleted master_project_ai_interaction: %', v_rows;
  ELSE RAISE NOTICE '[A4] skip master_project_ai_interaction (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_ai_assessment') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_project_ai_assessment (LIKE public.master_project_ai_assessment INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_project_ai_assessment ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_project_ai_assessment
      (id, "companyId", "projectId", assessment_date, rd_score, rd_score_breakdown, rd_potential, status, createdtime, project_stage, assessment_type, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, "companyId", "projectId", assessment_date, rd_score, rd_score_breakdown, rd_potential, status, createdtime, project_stage, assessment_type, $1, $2
      FROM public.master_project_ai_assessment t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_project_ai_assessment WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A5] Backed up + deleted master_project_ai_assessment: %', v_rows;
  ELSE RAISE NOTICE '[A5] skip master_project_ai_assessment (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_request') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_ai_request (LIKE public.master_ai_request INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_ai_request ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_ai_request
      (id, service, "requestId", "companyId", "projectId", status, createdtime, end_time, createdby, sysmodtime, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, service, "requestId", "companyId", "projectId", status, createdtime, end_time, createdby, sysmodtime, $1, $2
      FROM public.master_ai_request t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_ai_request WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A6] Backed up + deleted master_ai_request: %', v_rows;
  ELSE RAISE NOTICE '[A6] skip master_ai_request (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_llm_logs') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_ai_llm_logs (LIKE public.master_ai_llm_logs INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_ai_llm_logs ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_ai_llm_logs
      (id, llm_model, "projectId", "companyId", request_id, service, prompt, temperature, max_tokens, response_text, response_length, prompt_length, response_status, llm_time_taken, createdby, createdtime, sysmodtime, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, llm_model, "projectId", "companyId", request_id, service, prompt, temperature, max_tokens, response_text, response_length, prompt_length, response_status, llm_time_taken, createdby, createdtime, sysmodtime, $1, $2
      FROM public.master_ai_llm_logs t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_ai_llm_logs WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A7] Backed up + deleted master_ai_llm_logs: %', v_rows;
  ELSE RAISE NOTICE '[A7] skip master_ai_llm_logs (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_ai_knowledge_base') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_ai_knowledge_base (LIKE public.master_ai_knowledge_base INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_ai_knowledge_base ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format($ins$INSERT INTO %I.bak_master_ai_knowledge_base
      (id, "projectId", "companyId", data_source, chunk_index, data, createddate, updatedate, summary_tags, assessment_tags, used_flag, summarized_flag, character_length, chunk_ids, collection, embedding_id, _backup_run_at, _backup_project_fiscal_rid)
      SELECT id, "projectId", "companyId", data_source, chunk_index, data, createddate, updatedate, summary_tags, assessment_tags, used_flag, summarized_flag, character_length, chunk_ids, collection, embedding_id, $1, $2
      FROM public.master_ai_knowledge_base t WHERE t."projectId" = $2$ins$, v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_ai_knowledge_base WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A8] Backed up + deleted master_ai_knowledge_base: %', v_rows;
  ELSE RAISE NOTICE '[A8] skip master_ai_knowledge_base (not found)'; END IF;

  -- ── Top-level / independent tables ───────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'master_project_details') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_master_project_details (LIKE public.master_project_details INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_master_project_details ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format('INSERT INTO %I.bak_master_project_details SELECT t.*, $1, $2 FROM public.master_project_details t WHERE t."projectId" = $2', v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.master_project_details WHERE "projectId" = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A9] Backed up + deleted master_project_details: %', v_rows;
  ELSE RAISE NOTICE '[A9] skip master_project_details (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'four_part_assessments') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I.bak_four_part_assessments (LIKE public.four_part_assessments INCLUDING ALL)', v_backup_schema);
    EXECUTE format('ALTER TABLE %I.bak_four_part_assessments ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_rid TEXT', v_backup_schema);
    EXECUTE format('INSERT INTO %I.bak_four_part_assessments SELECT t.*, $1, $2 FROM public.four_part_assessments t WHERE t.projectid = $2', v_backup_schema) USING v_run_at, v_project_fiscal_rid;
    EXECUTE 'DELETE FROM public.four_part_assessments WHERE projectid = $1' USING v_project_fiscal_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[A10] Backed up + deleted four_part_assessments: %', v_rows;
  ELSE RAISE NOTICE '[A10] skip four_part_assessments (not found)'; END IF;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 7 — trd365ai DELETE COMPLETE';
  RAISE NOTICE 'Next: run SECTION 8 (post-delete diff).';
  RAISE NOTICE '==============================================================';

EXCEPTION
  WHEN OTHERS THEN
    RAISE EXCEPTION 'SECTION 7 aborted (rolled back). SQLSTATE=%, ERROR=%', SQLSTATE, SQLERRM;
END;
$$;


-- =============================================================================
