-- SECTION 2  ORG DB — Delete
-- Run on: thinkrd365_org   |   Run: AFTER Section 1
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
  v_schema_name       TEXT := 'trd365_01379';
  v_account_rid       TEXT := 'D001-4bf2b0a2-f11c-4941-b075-82e8682a1e20';
  v_project_rid       TEXT := 'D001-a9fc5b2a-8a2d-4895-bd28-817ae0b51f33';
  v_project_fiscal_id TEXT := 'D001-1d94f590-3bec-49ae-ad8d-7acb78e0cd81';
  v_is_last_fiscal    BOOLEAN := FALSE;

  v_rows       INT;
  v_tbl_exists BOOLEAN;
  v_fiscal_year_for_recompute INT;
  v_region_rids_for_recompute TEXT[];
  v_region_rid TEXT;
  v_project_code_for_recompute TEXT;
  v_case_rids_for_recompute TEXT[];
  v_case_rid TEXT;
  v_resource_rids_for_recompute TEXT[];
  v_resource_rid TEXT;
  v_resource_code TEXT;
BEGIN

  IF FALSE THEN  -- guard neutralized: values already filled correctly for this run
    RAISE EXCEPTION 'Fill in v_lookup_project_fiscal_id before running SECTION 2.';
  END IF;

  IF v_backup_schema = '<PASTE_BACKUP_SCHEMA_FROM_SECTION_1>' THEN
    RAISE EXCEPTION 'Paste the backup schema name from SECTION 1 output before running this section.';
  END IF;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 2 — ORG DB DELETE STARTED';
  RAISE NOTICE '  schema = %  |  fiscal = %  |  last_fiscal = %',
    v_schema_name, v_project_fiscal_id, v_is_last_fiscal;
  RAISE NOTICE '==============================================================';

  -- ── Interaction children ─────────────────────────────────────────────────
  -- Each DELETE below is preceded by a backup step: create <v_backup_schema>.bak_org_<table>
  -- (mirroring the source table's columns, plus _backup_run_at/_backup_project_fiscal_id),
  -- then INSERT INTO it a SELECT using the EXACT same join/filter as the DELETE that follows.

  -- interaction_attachments must be deleted BEFORE interaction_response_history:
  -- interaction_attachments.interaction_response_rid has an FK into
  -- interaction_response_history (interaction_response_rid_fkey) — deleting
  -- the parent first violates that constraint if any attachments reference it.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interaction_attachments (LIKE %I.interaction_attachments INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interaction_attachments ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_attachments SELECT ia.*, $1, $2 FROM %I.interaction_attachments ia, %I.interactions i WHERE ia.interaction_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.interaction_attachments ia USING %I.interactions i WHERE ia.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O4]  Backed up + deleted interaction_attachments: %', v_rows;
  ELSE RAISE NOTICE '[O4]  skip interaction_attachments (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_response_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interaction_response_history (LIKE %I.interaction_response_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interaction_response_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_response_history SELECT irh.*, $1, $2 FROM %I.interaction_response_history irh, %I.interaction_items ii, %I.interactions i WHERE irh.interaction_item_rid = ii.rid AND ii.interaction_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.interaction_response_history irh USING %I.interaction_items ii, %I.interactions i WHERE irh.interaction_item_rid = ii.rid AND ii.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    -- interaction_response_history ALSO has its own direct interaction_rid FK
    -- into interactions (interaction_rid_fkey), separate from the
    -- interaction_item_rid path above — some rows are only reachable this
    -- way, so they must be swept up here too or a later DELETE FROM
    -- interactions could fail with a FK violation.
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_response_history SELECT irh.*, $1, $2 FROM %I.interaction_response_history irh, %I.interactions i WHERE irh.interaction_rid = i.rid AND i.project_fiscal_rid = $2 AND NOT EXISTS (SELECT 1 FROM %I.bak_org_interaction_response_history b WHERE b.rid = irh.rid AND b._backup_run_at = $1)$sql$, v_backup_schema, v_schema_name, v_schema_name, v_backup_schema) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.interaction_response_history irh USING %I.interactions i WHERE irh.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O1]  Backed up + deleted interaction_response_history: %', v_rows;
  ELSE RAISE NOTICE '[O1]  skip interaction_response_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_items') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interaction_items (LIKE %I.interaction_items INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interaction_items ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_items SELECT ii.*, $1, $2 FROM %I.interaction_items ii, %I.interactions i WHERE ii.interaction_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_items SELECT ii.*, $1, $2 FROM %I.interaction_items ii WHERE ii.project_fiscal_rid = $2 AND NOT EXISTS (SELECT 1 FROM %I.bak_org_interaction_items b WHERE b.rid = ii.rid AND b._backup_run_at = $1)$sql$, v_backup_schema, v_schema_name, v_backup_schema) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.interaction_items ii USING %I.interactions i WHERE ii.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.interaction_items WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O2]  Backed up + deleted interaction_items: %', v_rows;
  ELSE RAISE NOTICE '[O2]  skip interaction_items (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interaction_timeline (LIKE %I.interaction_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interaction_timeline ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_timeline SELECT it.*, $1, $2 FROM %I.interaction_timeline it, %I.interactions i WHERE it.entity_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.interaction_timeline it USING %I.interactions i WHERE it.entity_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O3]  Backed up + deleted interaction_timeline: %', v_rows;
  ELSE RAISE NOTICE '[O3]  skip interaction_timeline (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interaction_history (LIKE %I.interaction_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interaction_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_history SELECT t.*, $1, $2 FROM %I.interaction_history t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.interaction_history WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O5]  Backed up + deleted interaction_history: %', v_rows;
  ELSE RAISE NOTICE '[O5]  skip interaction_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interaction_status_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interaction_status_history (LIKE %I.interaction_status_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interaction_status_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interaction_status_history SELECT ish.*, $1, $2 FROM %I.interaction_status_history ish, %I.interactions i WHERE ish.interaction_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.interaction_status_history ish USING %I.interactions i WHERE ish.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O6]  Backed up + deleted interaction_status_history: %', v_rows;
  ELSE RAISE NOTICE '[O6]  skip interaction_status_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'otp_entries_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_otp_entries_history (LIKE %I.otp_entries_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_otp_entries_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_otp_entries_history SELECT oeh.*, $1, $2 FROM %I.otp_entries_history oeh, %I.interactions i WHERE oeh.interaction_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$INSERT INTO %I.bak_org_otp_entries_history SELECT oeh.*, $1, $2 FROM %I.otp_entries_history oeh WHERE oeh.project_fiscal_rid = $2 AND oeh.account_rid = $3 AND NOT EXISTS (SELECT 1 FROM %I.bak_org_otp_entries_history b WHERE b.rid = oeh.rid AND b._backup_run_at = $1)$sql$, v_backup_schema, v_schema_name, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    EXECUTE format($sql$DELETE FROM %I.otp_entries_history oeh USING %I.interactions i WHERE oeh.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.otp_entries_history WHERE project_fiscal_rid = $1 AND account_rid = $2', v_schema_name) USING v_project_fiscal_id, v_account_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O7]  Backed up + deleted otp_entries_history: %', v_rows;
  ELSE RAISE NOTICE '[O7]  skip otp_entries_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'otp_entries') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_otp_entries (LIKE %I.otp_entries INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_otp_entries ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_otp_entries SELECT oe.*, $1, $2 FROM %I.otp_entries oe, %I.interactions i WHERE oe.interaction_rid = i.rid AND i.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$INSERT INTO %I.bak_org_otp_entries SELECT oe.*, $1, $2 FROM %I.otp_entries oe WHERE oe.project_fiscal_rid = $2 AND oe.account_rid = $3 AND NOT EXISTS (SELECT 1 FROM %I.bak_org_otp_entries b WHERE b.rid = oe.rid AND b._backup_run_at = $1)$sql$, v_backup_schema, v_schema_name, v_backup_schema) USING v_run_at, v_project_fiscal_id, v_account_rid;
    EXECUTE format($sql$DELETE FROM %I.otp_entries oe USING %I.interactions i WHERE oe.interaction_rid = i.rid AND i.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.otp_entries WHERE project_fiscal_rid = $1 AND account_rid = $2', v_schema_name) USING v_project_fiscal_id, v_account_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O8]  Backed up + deleted otp_entries: %', v_rows;
  ELSE RAISE NOTICE '[O8]  skip otp_entries (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'interactions') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_interactions (LIKE %I.interactions INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_interactions ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_interactions SELECT t.*, $1, $2 FROM %I.interactions t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.interactions WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O9]  Backed up + deleted interactions: %', v_rows;
  ELSE RAISE NOTICE '[O9]  skip interactions (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'four_part_assessment') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_four_part_assessment (LIKE %I.four_part_assessment INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_four_part_assessment ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_four_part_assessment SELECT t.*, $1, $2 FROM %I.four_part_assessment t WHERE t.project_fiscal_rid = $2 AND t.account_rid = $3$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_account_rid;
    EXECUTE format('DELETE FROM %I.four_part_assessment WHERE project_fiscal_rid = $1 AND account_rid = $2', v_schema_name) USING v_project_fiscal_id, v_account_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O10] Backed up + deleted four_part_assessment: %', v_rows;
  ELSE RAISE NOTICE '[O10] skip four_part_assessment (not found)'; END IF;

  -- ── Task children ────────────────────────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_task_timeline (LIKE %I.project_task_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_task_timeline ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_task_timeline SELECT t.*, $1, $2 FROM %I.project_task_timeline t WHERE t.entity_rid IN (SELECT rid FROM %I.project_task WHERE project_fiscal_rid = $2)$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.project_task_timeline WHERE entity_rid IN (SELECT rid FROM %I.project_task WHERE project_fiscal_rid = $1)$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O11] Backed up + deleted project_task_timeline: %', v_rows;
  ELSE RAISE NOTICE '[O11] skip project_task_timeline (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_task_history (LIKE %I.project_task_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_task_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_task_history SELECT pth.*, $1, $2 FROM %I.project_task_history pth, %I.project_task pt WHERE pth.project_task_rid = pt.rid AND pt.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.project_task_history pth USING %I.project_task pt WHERE pth.project_task_rid = pt.rid AND pt.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O12] Backed up + deleted project_task_history: %', v_rows;
  ELSE RAISE NOTICE '[O12] skip project_task_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_tags') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_task_tags (LIKE %I.task_tags INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_task_tags ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_task_tags SELECT tt.*, $1, $2 FROM %I.task_tags tt, %I.project_task pt WHERE tt.task_rid = pt.rid AND pt.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.task_tags tt USING %I.project_task pt WHERE tt.task_rid = pt.rid AND pt.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O13] Backed up + deleted task_tags: %', v_rows;
  ELSE RAISE NOTICE '[O13] skip task_tags (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_comments') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_task_comments (LIKE %I.task_comments INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_task_comments ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_task_comments SELECT tc.*, $1, $2 FROM %I.task_comments tc, %I.project_task pt WHERE tc.task_rid = pt.rid AND pt.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.task_comments tc USING %I.project_task pt WHERE tc.task_rid = pt.rid AND pt.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O14] Backed up + deleted task_comments: %', v_rows;
  ELSE RAISE NOTICE '[O14] skip task_comments (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_collaborators') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_task_collaborators (LIKE %I.task_collaborators INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_task_collaborators ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_task_collaborators SELECT tc.*, $1, $2 FROM %I.task_collaborators tc, %I.project_task pt WHERE tc.task_rid = pt.rid AND pt.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.task_collaborators tc USING %I.project_task pt WHERE tc.task_rid = pt.rid AND pt.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O15] Backed up + deleted task_collaborators: %', v_rows;
  ELSE RAISE NOTICE '[O15] skip task_collaborators (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_task_attachments (LIKE %I.task_attachments INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_task_attachments ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_task_attachments SELECT ta.*, $1, $2 FROM %I.task_attachments ta, %I.project_task pt WHERE ta.task_rid = pt.rid AND pt.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.task_attachments ta USING %I.project_task pt WHERE ta.task_rid = pt.rid AND pt.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O16] Backed up + deleted task_attachments: %', v_rows;
  ELSE RAISE NOTICE '[O16] skip task_attachments (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'task_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_task_history (LIKE %I.task_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_task_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_task_history SELECT th.*, $1, $2 FROM %I.task_history th, %I.project_task pt WHERE th.task_rid = pt.rid AND pt.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.task_history th USING %I.project_task pt WHERE th.task_rid = pt.rid AND pt.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O17] Backed up + deleted task_history: %', v_rows;
  ELSE RAISE NOTICE '[O17] skip task_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_task') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_task (LIKE %I.project_task INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_task ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_task SELECT t.*, $1, $2 FROM %I.project_task t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_task WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O18] Backed up + deleted project_task: %', v_rows;
  ELSE RAISE NOTICE '[O18] skip project_task (not found)'; END IF;

  -- ── Resource children ────────────────────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_fiscal_region') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_resource_fiscal_region (LIKE %I.project_resource_fiscal_region INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_resource_fiscal_region ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_resource_fiscal_region SELECT t.*, $1, $2 FROM %I.project_resource_fiscal_region t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_resource_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O19] Backed up + deleted project_resource_fiscal_region: %', v_rows;
  ELSE RAISE NOTICE '[O19] skip project_resource_fiscal_region (not found)'; END IF;

  -- Capture case_rids and resource_rids linked to this project_fiscal's
  -- resource data BEFORE the deletes below — needed to recompute
  -- case_projects/case_project_fiscal_region (case-scoped rollups) and
  -- resource_fiscal/resource_fiscal_region (resource-scoped rollups)
  -- afterward, since both are sourced from data being deleted in this block.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'case_project_resource') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format('SELECT ARRAY_AGG(DISTINCT case_rid) FROM %I.case_project_resource WHERE project_fiscal_rid = $1', v_schema_name) INTO v_case_rids_for_recompute USING v_project_fiscal_id;
  END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_fiscal') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_resource_fiscal (LIKE %I.project_resource_fiscal INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_resource_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_resource_fiscal SELECT t.*, $1, $2 FROM %I.project_resource_fiscal t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_resource_fiscal WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O20] Backed up + deleted project_resource_fiscal: %', v_rows;
  ELSE RAISE NOTICE '[O20] skip project_resource_fiscal (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_resource_timeline (LIKE %I.project_resource_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_resource_timeline ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_resource_timeline SELECT prt.*, $1, $2 FROM %I.project_resource_timeline prt, %I.project_resource pr WHERE prt.entity_rid = pr.rid AND pr.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.project_resource_timeline prt USING %I.project_resource pr WHERE prt.entity_rid = pr.rid AND pr.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O21] Backed up + deleted project_resource_timeline: %', v_rows;
  ELSE RAISE NOTICE '[O21] skip project_resource_timeline (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_resource_history (LIKE %I.project_resource_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_resource_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_resource_history SELECT prh.*, $1, $2 FROM %I.project_resource_history prh, %I.project_resource pr WHERE prh.project_resource_rid = pr.rid AND pr.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.project_resource_history prh USING %I.project_resource pr WHERE prh.project_resource_rid = pr.rid AND pr.project_fiscal_rid = $1$sql$, v_schema_name, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O22] Backed up + deleted project_resource_history: %', v_rows;
  ELSE RAISE NOTICE '[O22] skip project_resource_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_resource') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    -- Capture the distinct resource_rids affected BEFORE the delete below —
    -- needed to recompute resource_fiscal/resource_fiscal_region afterward.
    EXECUTE format('SELECT ARRAY_AGG(DISTINCT resource_rid) FROM %I.project_resource WHERE project_fiscal_rid = $1', v_schema_name) INTO v_resource_rids_for_recompute USING v_project_fiscal_id;

    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_resource (LIKE %I.project_resource INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_resource ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_resource SELECT t.*, $1, $2 FROM %I.project_resource t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_resource WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O23] Backed up + deleted project_resource: %', v_rows;
  ELSE RAISE NOTICE '[O23] skip project_resource (not found)'; END IF;

  -- ── AI / assessment ──────────────────────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_technical_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_ai_technical_summary (LIKE %I.ai_technical_summary INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_ai_technical_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_ai_technical_summary SELECT t.*, $1, $2 FROM %I.ai_technical_summary t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.ai_technical_summary WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O24] Backed up + deleted ai_technical_summary: %', v_rows;
  ELSE RAISE NOTICE '[O24] skip ai_technical_summary (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_audit') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_ai_assessment_audit (LIKE %I.ai_assessment_audit INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_ai_assessment_audit ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_ai_assessment_audit SELECT t.*, $1, $2 FROM %I.ai_assessment_audit t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.ai_assessment_audit WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O25] Backed up + deleted ai_assessment_audit: %', v_rows;
  ELSE RAISE NOTICE '[O25] skip ai_assessment_audit (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_error') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_ai_assessment_error (LIKE %I.ai_assessment_error INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_ai_assessment_error ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_ai_assessment_error SELECT t.*, $1, $2 FROM %I.ai_assessment_error t WHERE t.account_rid = $3 AND t.project_rid IN (SELECT project_rid FROM %I.project_fiscal WHERE rid = $2)$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id, v_account_rid;
    EXECUTE format($sql$DELETE FROM %I.ai_assessment_error WHERE account_rid = $1 AND project_rid IN (SELECT project_rid FROM %I.project_fiscal WHERE rid = $2)$sql$, v_schema_name, v_schema_name) USING v_account_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O26] Backed up + deleted ai_assessment_error: %', v_rows;
  ELSE RAISE NOTICE '[O26] skip ai_assessment_error (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'ai_assessment_qre') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_ai_assessment_qre (LIKE %I.ai_assessment_qre INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_ai_assessment_qre ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_ai_assessment_qre SELECT t.*, $1, $2 FROM %I.ai_assessment_qre t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.ai_assessment_qre WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O27] Backed up + deleted ai_assessment_qre: %', v_rows;
  ELSE RAISE NOTICE '[O27] skip ai_assessment_qre (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'autosend_interaction_audit') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_autosend_interaction_audit (LIKE %I.autosend_interaction_audit INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_autosend_interaction_audit ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_autosend_interaction_audit SELECT t.*, $1, $2 FROM %I.autosend_interaction_audit t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.autosend_interaction_audit WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O28] Backed up + deleted autosend_interaction_audit: %', v_rows;
  ELSE RAISE NOTICE '[O28] skip autosend_interaction_audit (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_qre_adjustment_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_qre_adjustment_history (LIKE %I.project_qre_adjustment_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_qre_adjustment_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_qre_adjustment_history SELECT t.*, $1, $2 FROM %I.project_qre_adjustment_history t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_qre_adjustment_history WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29] Backed up + deleted project_qre_adjustment_history: %', v_rows;
  ELSE RAISE NOTICE '[O29] skip project_qre_adjustment_history (not found)'; END IF;

  -- ── Activities / notes / attachments ─────────────────────────────────────
  -- These all run on EVERY fiscal deletion, not just the last one. Some rows
  -- have attach_to = project_fiscal_id despite attachment_level = 'project'
  -- (a mislabeled/legacy data shape), so matching on attach_to = v_project_rid
  -- alone silently misses them. Matched by attach_to IN (project_rid,
  -- project_fiscal_id), and NOT also filtered on attachment_level, so both
  -- correctly-labeled and mislabeled rows are always caught — by both the
  -- delete here and the Section 1 pre-count / Section 4 post-count.
  --
  -- The parent `project` row deletion is deferred until AFTER the fiscal row
  -- itself is deleted below — project_fiscal.project_rid FKs to project.rid,
  -- so deleting the parent first (while project_fiscal still exists) would
  -- violate that FK.

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activity_attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_activity_attachments (LIKE %I.activity_attachments INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_activity_attachments ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_activity_attachments SELECT aa.*, $1, $2 FROM %I.activity_attachments aa, %I.activities a WHERE aa.activity_rid = a.rid AND a.attach_to IN ($3, $2)$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format($sql$DELETE FROM %I.activity_attachments aa USING %I.activities a WHERE aa.activity_rid = a.rid AND a.attach_to IN ($1, $2)$sql$, v_schema_name, v_schema_name) USING v_project_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29a] Backed up + deleted activity_attachments (project): %', v_rows;
  ELSE RAISE NOTICE '[O29a] skip activity_attachments (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activity_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_activity_history (LIKE %I.activity_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_activity_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_activity_history SELECT ah.*, $1, $2 FROM %I.activity_history ah, %I.activities a WHERE ah.activity_rid = a.rid AND a.attach_to IN ($3, $2)$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format($sql$DELETE FROM %I.activity_history ah USING %I.activities a WHERE ah.activity_rid = a.rid AND a.attach_to IN ($1, $2)$sql$, v_schema_name, v_schema_name) USING v_project_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29b] Backed up + deleted activity_history (project): %', v_rows;
  ELSE RAISE NOTICE '[O29b] skip activity_history (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'meeting_summary') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_meeting_summary (LIKE %I.meeting_summary INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_meeting_summary ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_meeting_summary SELECT ms.*, $1, $2 FROM %I.meeting_summary ms, %I.activities a WHERE ms.activity_rid = a.rid AND a.attach_to IN ($3, $2)$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format($sql$DELETE FROM %I.meeting_summary ms USING %I.activities a WHERE ms.activity_rid = a.rid AND a.attach_to IN ($1, $2)$sql$, v_schema_name, v_schema_name) USING v_project_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29c] Backed up + deleted meeting_summary (project): %', v_rows;
  ELSE RAISE NOTICE '[O29c] skip meeting_summary (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'activities') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_activities (LIKE %I.activities INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_activities ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_activities SELECT t.*, $1, $2 FROM %I.activities t WHERE t.attach_to IN ($3, $2)$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format($sql$DELETE FROM %I.activities WHERE attach_to IN ($1, $2)$sql$, v_schema_name) USING v_project_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29d] Backed up + deleted activities (project): %', v_rows;
  ELSE RAISE NOTICE '[O29d] skip activities (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'notes') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_notes_timeline (LIKE %I.notes_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_notes_timeline ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_notes_timeline SELECT t.*, $1, $2 FROM %I.notes_timeline t WHERE t.attach_to IN (SELECT rid FROM %I.notes WHERE attach_to IN ($3, $2))$sql$, v_backup_schema, v_schema_name, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format($sql$DELETE FROM %I.notes_timeline WHERE attach_to IN (SELECT rid FROM %I.notes WHERE attach_to IN ($1, $2))$sql$, v_schema_name, v_schema_name) USING v_project_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29f] Backed up + deleted notes_timeline (project): %', v_rows;

    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_notes (LIKE %I.notes INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_notes ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_notes SELECT t.*, $1, $2 FROM %I.notes t WHERE t.attach_to IN ($3, $2)$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format($sql$DELETE FROM %I.notes WHERE attach_to IN ($1, $2)$sql$, v_schema_name) USING v_project_rid, v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29g] Backed up + deleted notes (project): %', v_rows;
  ELSE RAISE NOTICE '[O29f-g] skip notes/notes_timeline (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'attachments') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_attachments (LIKE %I.attachments INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_attachments ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_attachments SELECT t.*, $1, $2 FROM %I.attachments t WHERE t.attach_to = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format($sql$DELETE FROM %I.attachments WHERE attach_to = $1$sql$, v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O29e] Backed up + deleted attachments (project_fiscal): %', v_rows;
  ELSE RAISE NOTICE '[O29e] skip attachments (not found)'; END IF;

  -- ── Fiscal row itself ────────────────────────────────────────────────────

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_fiscal_region') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    -- Capture the distinct region_rids affected BEFORE the delete below —
    -- needed to recompute account_fiscal_region afterward (that table is
    -- keyed by account_rid + fiscal_year + region_rid, one row per region).
    EXECUTE format('SELECT ARRAY_AGG(DISTINCT region_rid) FROM %I.project_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) INTO v_region_rids_for_recompute USING v_project_fiscal_id;

    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_fiscal_region (LIKE %I.project_fiscal_region INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_fiscal_region ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_fiscal_region SELECT t.*, $1, $2 FROM %I.project_fiscal_region t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_fiscal_region WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O31] Backed up + deleted project_fiscal_region: %', v_rows;
  ELSE RAISE NOTICE '[O31] skip project_fiscal_region (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_history_fiscal (LIKE %I.project_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_history_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_history_fiscal SELECT t.*, $1, $2 FROM %I.project_history t WHERE t.project_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_history WHERE project_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O32] Backed up + deleted project_history (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[O32] skip project_history fiscal (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_timeline_fiscal (LIKE %I.project_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_timeline_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_timeline_fiscal SELECT t.*, $1, $2 FROM %I.project_timeline t WHERE t.entity_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_timeline WHERE entity_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O33] Backed up + deleted project_timeline (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[O33] skip project_timeline fiscal (not found)'; END IF;

  -- project_timeline_old has an FK (project_timeline_entity_rid_fkey) into
  -- project_fiscal via entity_rid, same as project_timeline — must be cleared
  -- BEFORE project_fiscal itself is deleted below, or that DELETE fails with
  -- a FK violation.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline_old') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_timeline_old_fiscal (LIKE %I.project_timeline_old INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_timeline_old_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_timeline_old_fiscal SELECT t.*, $1, $2 FROM %I.project_timeline_old t WHERE t.entity_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_timeline_old WHERE entity_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O33b] Backed up + deleted project_timeline_old (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[O33b] skip project_timeline_old fiscal (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'account_timeline') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_account_timeline_fiscal (LIKE %I.account_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_account_timeline_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_account_timeline_fiscal SELECT t.*, $1, $2 FROM %I.account_timeline t WHERE t.entity_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.account_timeline WHERE entity_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O34] Backed up + deleted account_timeline (fiscal): %', v_rows;
  ELSE RAISE NOTICE '[O34] skip account_timeline (not found)'; END IF;

  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_fiscal_history') INTO v_tbl_exists;
  IF v_tbl_exists THEN
    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_fiscal_history (LIKE %I.project_fiscal_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_fiscal_history ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_fiscal_history SELECT t.*, $1, $2 FROM %I.project_fiscal_history t WHERE t.project_fiscal_rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
    EXECUTE format('DELETE FROM %I.project_fiscal_history WHERE project_fiscal_rid = $1', v_schema_name) USING v_project_fiscal_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O35] Backed up + deleted project_fiscal_history: %', v_rows;
  ELSE RAISE NOTICE '[O35] skip project_fiscal_history (not found)'; END IF;

  -- Capture fiscal_year BEFORE the delete below — account_fiscal is keyed by
  -- (account_rid, fiscal_year), not by project_fiscal_rid, so we need this to
  -- recompute account_fiscal's rollup afterward.
  EXECUTE format('SELECT fiscal_year FROM %I.project_fiscal WHERE rid = $1', v_schema_name) INTO v_fiscal_year_for_recompute USING v_project_fiscal_id;
  EXECUTE format('SELECT project_code FROM %I.project_fiscal WHERE rid = $1', v_schema_name) INTO v_project_code_for_recompute USING v_project_fiscal_id;

  EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_fiscal (LIKE %I.project_fiscal INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
  EXECUTE format('ALTER TABLE %I.bak_org_project_fiscal ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
  EXECUTE format($sql$INSERT INTO %I.bak_org_project_fiscal SELECT t.*, $1, $2 FROM %I.project_fiscal t WHERE t.rid = $2$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id;
  EXECUTE format('DELETE FROM %I.project_fiscal WHERE rid = $1', v_schema_name) USING v_project_fiscal_id;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  RAISE NOTICE '[O36] Backed up + deleted project_fiscal: %', v_rows;

  -- Re-aggregate account_fiscal's project_resource-derived rollup columns
  -- for this account+fiscal_year, now that this project's project_fiscal row
  -- (and its project_resource_fiscal rows, deleted earlier at [O20]) are
  -- gone. Re-sums directly from whatever project_fiscal rows remain for this
  -- account+year — the deleted project's row is naturally excluded since it
  -- no longer exists. Mirrors ONLY the columns the live application's own
  -- aggregatesAccountFiscal() actually writes today
  -- (entity-module/src/services/projectResource/schemaService.ts:5413-5439):
  -- total_projects/total_project_cost/total_project_hours/total_fte/
  -- total_subcon are deliberately NOT recomputed here because that function
  -- has those five target fields commented out in the live app — a
  -- pre-existing app-level inconsistency, not something this deletion
  -- script should paper over by doing more than the app itself does.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'account_fiscal') INTO v_tbl_exists;
  IF v_tbl_exists AND v_fiscal_year_for_recompute IS NOT NULL THEN
    EXECUTE format($sql$
      UPDATE %I.account_fiscal SET
        total_project_res_cost          = (SELECT COALESCE(SUM(total_cost_from_prj_res),         0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        total_project_res_hours         = (SELECT COALESCE(SUM(total_effort_from_prj_res),        0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        total_project_res_hours_fte     = (SELECT COALESCE(SUM(total_effort_fte_from_prj_res),    0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        total_project_res_hours_subcon  = (SELECT COALESCE(SUM(total_effort_subcon_from_prj_res), 0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        total_project_res_cost_fte      = (SELECT COALESCE(SUM(total_cost_fte_from_prj_res),      0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        total_project_res_cost_subcon   = (SELECT COALESCE(SUM(total_cost_subcon_from_prj_res),   0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        total_project_res_cost_nonlabor = (SELECT COALESCE(SUM(total_cost_nonlabor_from_prj_res), 0) FROM %I.project_fiscal WHERE account_rid = $1 AND fiscal_year = $2),
        modified_datetime = NOW()
      WHERE account_rid = $1 AND fiscal_year = $2
    $sql$, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name)
      USING v_account_rid, v_fiscal_year_for_recompute;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O36b] Recomputed account_fiscal (project_resource rollup columns only): %', v_rows;
  ELSE
    RAISE NOTICE '[O36b] skip account_fiscal recompute (table not found or fiscal_year unresolved)';
  END IF;

  -- Recompute account_fiscal_region for every region this project's fiscal
  -- data touched (captured above at [O31], before project_fiscal_region was
  -- deleted). Unlike account_fiscal, aggregatesAccountFiscalRegion
  -- (entity-module/src/services/projectResource/schemaService.ts:5549-5572)
  -- DOES actively write total_projects/total_project_cost/total_project_hours/
  -- total_fte/total_subcon (not commented out there, unlike the account-level
  -- sibling function) — so all 10 target columns below are recomputed, not 7.
  -- Matched by account_rid + fiscal_year + region_rid, one UPDATE per region.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'account_fiscal_region') INTO v_tbl_exists;
  IF v_tbl_exists AND v_fiscal_year_for_recompute IS NOT NULL AND v_region_rids_for_recompute IS NOT NULL THEN
    FOREACH v_region_rid IN ARRAY v_region_rids_for_recompute LOOP
      CONTINUE WHEN v_region_rid IS NULL;
      EXECUTE format($sql$
        UPDATE %I.account_fiscal_region SET
          total_projects                   = (SELECT COUNT(DISTINCT project_code)                        FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_cost               = (SELECT COALESCE(SUM(effective_cost),                    0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_hours              = (SELECT COALESCE(SUM(effective_effort),                  0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_fte                        = (SELECT COALESCE(SUM(effective_total_fte),               0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_subcon                     = (SELECT COALESCE(SUM(effective_total_subcon),             0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_res_hours_fte      = (SELECT COALESCE(SUM(effective_fte_effort),               0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_res_hours_subcon   = (SELECT COALESCE(SUM(effective_subcon_effort),            0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_res_cost_fte       = (SELECT COALESCE(SUM(effective_fte_cost),                 0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_res_cost_subcon    = (SELECT COALESCE(SUM(effective_subcon_cost),              0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          total_project_res_cost_nonlabor  = (SELECT COALESCE(SUM(effective_nonlabor_cost),            0) FROM %I.project_fiscal_region WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3),
          modified_datetime = NOW()
        WHERE account_rid = $1 AND fiscal_year = $2 AND region_rid = $3
      $sql$, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name)
        USING v_account_rid, v_fiscal_year_for_recompute, v_region_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O31b] Recomputed account_fiscal_region for region %: %', v_region_rid, v_rows;
    END LOOP;
  ELSE
    RAISE NOTICE '[O31b] skip account_fiscal_region recompute (table not found, fiscal_year unresolved, or no regions captured)';
  END IF;

  -- Recompute the `project` table's own rollup columns (org DB), matched by
  -- project_code + account_rid — mirrors entity-module's own
  -- updateProjectAggregatesFromFiscal (projectIngestionService.ts:725-801),
  -- EXCEPT that function has a confirmed bug: when zero project_fiscal rows
  -- remain for a project (its findOne(...) with GROUP BY returns no row at
  -- all), the live app's code does `if (!aggregates) return;` and SILENTLY
  -- SKIPS the update — leaving `project`'s totals stranded at their last
  -- pre-deletion values instead of zeroing them out. This is a real,
  -- confirmed-in-production gap (found via direct DB inspection after a
  -- project's only fiscal year was deleted: project.total_cost/total_effort
  -- remained non-zero with modified_datetime = NULL, i.e. never touched).
  -- This recompute uses explicit COALESCE(..., 0) so it correctly zeroes out
  -- `project`'s totals when no project_fiscal rows remain, unlike the app.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project') INTO v_tbl_exists;
  IF v_tbl_exists AND v_project_code_for_recompute IS NOT NULL THEN
    EXECUTE format($sql$
      UPDATE %I.project SET
        total_cost           = (SELECT COALESCE(SUM(total_cost_prj),           0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_effort          = (SELECT COALESCE(SUM(total_effort_prj),         0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_fte             = (SELECT COALESCE(SUM(total_fte_prj),            0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_subcon          = (SELECT COALESCE(SUM(total_subcon_prj),         0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_nonlabor        = (SELECT COALESCE(SUM(total_nonlabor_prj),       0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_effort_fte      = (SELECT COALESCE(SUM(total_effort_fte_prj),     0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_effort_subcon   = (SELECT COALESCE(SUM(total_effort_subcon_prj),  0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_cost_fte        = (SELECT COALESCE(SUM(total_cost_fte_prj),      0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_cost_subcon     = (SELECT COALESCE(SUM(total_cost_subcon_prj),   0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        total_cost_nonlabor   = (SELECT COALESCE(SUM(total_cost_nonlabor_prj), 0) FROM %I.project_fiscal WHERE project_code = $1 AND account_rid = $2),
        modified_datetime = NOW()
      WHERE project_code = $1 AND account_rid = $2
    $sql$, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name, v_schema_name)
      USING v_project_code_for_recompute, v_account_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O36c] Recomputed project rollup columns: %', v_rows;
  ELSE
    RAISE NOTICE '[O36c] skip project recompute (table not found or project_code unresolved)';
  END IF;

  -- Recompute case_projects for every case this project's fiscal data was
  -- linked to (captured above from case_project_resource). Mirrors
  -- entity-module's aggregatesCaseProjectFiscal
  -- (projectResource/schemaService.ts:4328-4546), which sums
  -- net_total_cost_pro_res/total_hours_pro_res from case_project_resource.
  -- NOTE: the live function ALSO buckets by resource type (full-time/sub
  -- con/non-labor) into total_cost_fte_from_prj_res/total_cost_subcon_from_
  -- prj_res/total_cost_nonlabor_from_prj_res — that requires joining
  -- resources.resource_type_rid to the resource_type lookup TABLE, which
  -- lives in MAIN DB (trd365.resource_type), a SEPARATE Postgres server
  -- from this ORG DB connection (confirmed: main-db-endpoint and
  -- org-db-endpoint are different Azure Postgres hosts — no cross-server
  -- SQL JOIN is possible from a single DO block here). Recomputing the
  -- per-type breakdown would require a two-step app-side join (fetch
  -- resource_type rows from MAIN DB separately, map in application code),
  -- which this SQL-only script cannot do. This recompute is therefore
  -- intentionally limited to the two type-agnostic totals
  -- (total_cost_from_prj_res, total_effort_from_prj_res) — leaving
  -- total_cost_fte_from_prj_res/total_cost_subcon_from_prj_res/
  -- total_cost_nonlabor_from_prj_res un-recomputed is a known, documented
  -- gap, not an oversight.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'case_projects') INTO v_tbl_exists;
  IF v_tbl_exists AND v_fiscal_year_for_recompute IS NOT NULL AND v_case_rids_for_recompute IS NOT NULL THEN
    FOREACH v_case_rid IN ARRAY v_case_rids_for_recompute LOOP
      CONTINUE WHEN v_case_rid IS NULL;
      EXECUTE format($sql$
        UPDATE %I.case_projects SET
          total_cost_from_prj_res   = (SELECT COALESCE(SUM(net_total_cost_pro_res), 0) FROM %I.case_project_resource WHERE account_rid = $1 AND fiscal_year = $2 AND project_fiscal_rid = $3 AND case_rid = $4),
          total_effort_from_prj_res = (SELECT COALESCE(SUM(total_hours_pro_res), 0) FROM %I.case_project_resource WHERE account_rid = $1 AND fiscal_year = $2 AND project_fiscal_rid = $3 AND case_rid = $4),
          modified_datetime = NOW()
        WHERE account_rid = $1 AND fiscal_year = $2 AND rid = $3 AND case_rid = $4
      $sql$, v_schema_name, v_schema_name, v_schema_name)
        USING v_account_rid, v_fiscal_year_for_recompute, v_project_fiscal_id, v_case_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O20b] Recomputed case_projects (type-agnostic totals only) for case %: %', v_case_rid, v_rows;
    END LOOP;
  ELSE
    RAISE NOTICE '[O20b] skip case_projects recompute (table not found, fiscal_year unresolved, or no cases linked)';
  END IF;

  -- Recompute resource_fiscal for every resource this project's fiscal data
  -- used (captured above from project_resource). CONFIRMED BUG in the live
  -- app's aggregatesResourceFiscal (projectResource/schemaService.ts:3981-
  -- 4044): its `if (!aggregates) return;` guard skips the UPDATE entirely
  -- when zero project_resource rows remain, leaving stale non-zero values
  -- (confirmed live in this exact database before this fix: resource_fiscal
  -- for res001/2024 still showed total_cost_for_year_project_resource_level
  -- = 293000.00 with modified_datetime = NULL after this project's resources
  -- were deleted). Match key confirmed as account_rid + fiscal_year +
  -- LOWER(resource_code) — NOT resource_rid, despite resource_rid being used
  -- to source the aggregate.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'resource_fiscal') INTO v_tbl_exists;
  IF v_tbl_exists AND v_fiscal_year_for_recompute IS NOT NULL AND v_resource_rids_for_recompute IS NOT NULL THEN
    FOREACH v_resource_rid IN ARRAY v_resource_rids_for_recompute LOOP
      CONTINUE WHEN v_resource_rid IS NULL;
      v_resource_code := NULL;
      EXECUTE format('SELECT resource_code FROM %I.resources WHERE rid = $1', v_schema_name) INTO v_resource_code USING v_resource_rid;
      CONTINUE WHEN v_resource_code IS NULL;
      EXECUTE format($sql$
        UPDATE %I.resource_fiscal SET
          total_effort_for_year_project_resource_level = (SELECT COALESCE(SUM(total_hours_pro_res), 0) FROM %I.project_resource WHERE account_rid = $1 AND resource_rid = $3 AND fiscal_year = $2),
          total_cost_for_year_project_resource_level    = (SELECT COALESCE(SUM(net_total_cost_pro_res), 0) FROM %I.project_resource WHERE account_rid = $1 AND resource_rid = $3 AND fiscal_year = $2),
          modified_datetime = NOW()
        WHERE account_rid = $1 AND fiscal_year = $2 AND LOWER(resource_code) = LOWER($4)
      $sql$, v_schema_name, v_schema_name, v_schema_name)
        USING v_account_rid, v_fiscal_year_for_recompute, v_resource_rid, v_resource_code;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O23b] Recomputed resource_fiscal for resource % (%): %', v_resource_rid, v_resource_code, v_rows;
    END LOOP;
  ELSE
    RAISE NOTICE '[O23b] skip resource_fiscal recompute (table not found, fiscal_year unresolved, or no resources captured)';
  END IF;

  -- Recompute resource_fiscal_region. CONFIRMED BUG in the live app's
  -- aggregatesResourceFiscalRegion (projectResource/schemaService.ts:4046-
  -- 4111): same "does nothing when zero source rows remain" pattern as
  -- resource_fiscal above. Additionally that function's own SELECT uses
  -- findOne+GROUP BY across multiple regions (an independent latent bug,
  -- not fixable here) — so this recompute enumerates every DISTINCT
  -- country_region_rid already present on resource_fiscal_region for this
  -- resource+year (the only reliable source of "which regions exist" after
  -- the fact) rather than trying to infer regions from deleted rows.
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'resource_fiscal_region') INTO v_tbl_exists;
  IF v_tbl_exists AND v_fiscal_year_for_recompute IS NOT NULL AND v_resource_rids_for_recompute IS NOT NULL THEN
    FOREACH v_resource_rid IN ARRAY v_resource_rids_for_recompute LOOP
      CONTINUE WHEN v_resource_rid IS NULL;
      v_resource_code := NULL;
      EXECUTE format('SELECT resource_code FROM %I.resources WHERE rid = $1', v_schema_name) INTO v_resource_code USING v_resource_rid;
      CONTINUE WHEN v_resource_code IS NULL;
      -- Correlated per-region update: Postgres does NOT allow `FROM LATERAL
      -- (...)` in an UPDATE to reference the target table being updated
      -- ("invalid reference to FROM-clause entry" — confirmed via direct
      -- test execution against this database; an earlier draft of this fix
      -- incorrectly assumed LATERAL would work here). A plain scalar
      -- subquery in SET (referencing the outer table directly, no alias/
      -- FROM needed) is the correct, Postgres-supported way to do a
      -- per-row correlated UPDATE.
      EXECUTE format($sql$
        UPDATE %I.resource_fiscal_region SET
          total_effort_for_year_project_resource_level = (
            SELECT COALESCE(SUM(pr.total_hours_pro_res), 0) FROM %I.project_resource pr
            WHERE pr.account_rid = $1 AND pr.resource_rid = $3 AND pr.fiscal_year = $2
              AND pr.region_rid = resource_fiscal_region.country_region_rid
          ),
          total_cost_for_year_project_resource_level = (
            SELECT COALESCE(SUM(pr.net_total_cost_pro_res), 0) FROM %I.project_resource pr
            WHERE pr.account_rid = $1 AND pr.resource_rid = $3 AND pr.fiscal_year = $2
              AND pr.region_rid = resource_fiscal_region.country_region_rid
          ),
          modified_datetime = NOW()
        WHERE account_rid = $1 AND fiscal_year = $2 AND LOWER(resource_code) = LOWER($4)
      $sql$, v_schema_name, v_schema_name, v_schema_name)
        USING v_account_rid, v_fiscal_year_for_recompute, v_resource_rid, v_resource_code;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O23c] Recomputed resource_fiscal_region for resource % (%): %', v_resource_rid, v_resource_code, v_rows;
    END LOOP;
  ELSE
    RAISE NOTICE '[O23c] skip resource_fiscal_region recompute (table not found, fiscal_year unresolved, or no resources captured)';
  END IF;

  -- ── Parent project rows (last fiscal only) ──────────────────────────────
  -- Runs AFTER project_fiscal is deleted above, since project_fiscal.project_rid
  -- FKs to project.rid — deleting project first would violate that FK.

  IF v_is_last_fiscal THEN

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_history') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_history_parent (LIKE %I.project_history INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
      EXECUTE format('ALTER TABLE %I.bak_org_project_history_parent ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_org_project_history_parent SELECT t.*, $1, $2 FROM %I.project_history t WHERE t.project_rid = $3$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
      EXECUTE format('DELETE FROM %I.project_history WHERE project_rid = $1', v_schema_name) USING v_project_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O30a] Backed up + deleted project_history (parent): %', v_rows;
    ELSE RAISE NOTICE '[O30a] skip project_history parent (not found)'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_timeline_parent (LIKE %I.project_timeline INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
      EXECUTE format('ALTER TABLE %I.bak_org_project_timeline_parent ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_org_project_timeline_parent SELECT t.*, $1, $2 FROM %I.project_timeline t WHERE t.entity_rid = $3$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
      EXECUTE format('DELETE FROM %I.project_timeline WHERE entity_rid = $1', v_schema_name) USING v_project_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O30b] Backed up + deleted project_timeline (parent): %', v_rows;
    ELSE RAISE NOTICE '[O30b] skip project_timeline parent (not found)'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'project_timeline_old') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_timeline_old_parent (LIKE %I.project_timeline_old INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
      EXECUTE format('ALTER TABLE %I.bak_org_project_timeline_old_parent ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_org_project_timeline_old_parent SELECT t.*, $1, $2 FROM %I.project_timeline_old t WHERE t.entity_rid = $3$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
      EXECUTE format('DELETE FROM %I.project_timeline_old WHERE entity_rid = $1', v_schema_name) USING v_project_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O30bb] Backed up + deleted project_timeline_old (parent): %', v_rows;
    ELSE RAISE NOTICE '[O30bb] skip project_timeline_old parent (not found)'; END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema_name AND table_name = 'key_contact_details') INTO v_tbl_exists;
    IF v_tbl_exists THEN
      EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_key_contact_details (LIKE %I.key_contact_details INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
      EXECUTE format('ALTER TABLE %I.bak_org_key_contact_details ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
      EXECUTE format($sql$INSERT INTO %I.bak_org_key_contact_details SELECT t.*, $1, $2 FROM %I.key_contact_details t WHERE t.entity_rid = $3$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
      EXECUTE format('DELETE FROM %I.key_contact_details WHERE entity_rid = $1', v_schema_name) USING v_project_rid;
      GET DIAGNOSTICS v_rows = ROW_COUNT;
      RAISE NOTICE '[O30c] Backed up + deleted key_contact_details (parent): %', v_rows;
    ELSE RAISE NOTICE '[O30c] skip key_contact_details (not found)'; END IF;

    EXECUTE format($sql$CREATE TABLE IF NOT EXISTS %I.bak_org_project_parent (LIKE %I.project INCLUDING ALL)$sql$, v_backup_schema, v_schema_name);
    EXECUTE format('ALTER TABLE %I.bak_org_project_parent ADD COLUMN IF NOT EXISTS _backup_run_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS _backup_project_fiscal_id TEXT', v_backup_schema);
    EXECUTE format($sql$INSERT INTO %I.bak_org_project_parent SELECT t.*, $1, $2 FROM %I.project t WHERE t.rid = $3$sql$, v_backup_schema, v_schema_name) USING v_run_at, v_project_fiscal_id, v_project_rid;
    EXECUTE format('DELETE FROM %I.project WHERE rid = $1', v_schema_name) USING v_project_rid;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RAISE NOTICE '[O30d] Backed up + deleted project (parent): %', v_rows;

  ELSE
    RAISE NOTICE '[O30]   Skipped parent project rows — other fiscals remain.';
  END IF;

  RAISE NOTICE '==============================================================';
  RAISE NOTICE 'SECTION 2 — ORG DB DELETE COMPLETE';
  RAISE NOTICE 'Next: switch to MAIN DB and run SECTION 3.';
  RAISE NOTICE '==============================================================';

EXCEPTION
  WHEN OTHERS THEN
    RAISE EXCEPTION 'SECTION 2 aborted (rolled back). SQLSTATE=%, ERROR=%', SQLSTATE, SQLERRM;
END;
$$;


-- =============================================================================
