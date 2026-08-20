"""The report is the artefact an operator reads afterwards, and the only one."""

from __future__ import annotations

import json

from trd365_data_purge.checkpoint import Checkpoint
from trd365_data_purge.reporting import render_text, summarise, write_report


def checkpoint(**overrides) -> Checkpoint:
    values = {
        "entity": "account",
        "entity_rid": "ACCT-1",
        "environment": "dev",
        "run_id": "run-1",
        "metrics": {
            "org_delete": {
                "_step_seconds": 1.5,
                "cases": {
                    "status": "ok", "scope_before": 4, "deleted": 4, "backed_up": 4,
                    "total_before": 10, "total_after": 6,
                },
                "empty_one": {"status": "empty", "scope_before": 0, "deleted": 0, "backed_up": 0},
                "mystery": {
                    "status": "unscoped", "scope_before": 0, "deleted": 0, "backed_up": 0,
                    "note": "no scope column; NOT touched",
                },
            }
        },
    }
    values.update(overrides)
    return Checkpoint(**values)


def test_summarise_ignores_the_step_timing_entry():
    totals = summarise(checkpoint())
    assert totals["tables_processed"] == 3


def test_summarise_totals_rows_and_names_unscoped_tables():
    totals = summarise(checkpoint())
    assert totals["rows_deleted"] == 4
    assert totals["rows_backed_up"] == 4
    assert totals["rows_in_scope"] == 4
    assert totals["tables_with_rows"] == 1
    assert totals["unscoped_tables"] == ["org_delete/mystery"]


def test_summarise_of_an_untouched_run_is_all_zero():
    totals = summarise(checkpoint(metrics={}))
    assert totals["rows_deleted"] == 0
    assert totals["unscoped_tables"] == []


def test_the_report_says_which_mode_it_was():
    assert "DRY RUN" in render_text(checkpoint(), applied=False)
    assert "APPLY" in render_text(checkpoint(), applied=True)


def test_a_dry_run_report_does_not_claim_the_audit_passed():
    assert "AUDIT: not performed (dry run)" in render_text(checkpoint(), applied=False)


def test_the_report_lists_unscoped_tables_prominently():
    text = render_text(checkpoint(), applied=True)
    assert "UNSCOPED — left untouched, need manual review:" in text
    assert "org_delete/mystery" in text


def test_tables_with_nothing_in_scope_are_not_listed():
    assert "empty_one" not in render_text(checkpoint(), applied=True)


def test_audit_findings_are_spelled_out():
    text = render_text(
        checkpoint(
            audit_clean=False,
            findings=[{"step": "org_delete", "table": "cases", "issues": ["3 rows still present"]}],
        ),
        applied=True,
    )
    assert "AUDIT: 1 FINDING(S)" in text
    assert "org_delete/cases: 3 rows still present" in text


def test_a_failure_is_carried_into_the_report():
    assert "ERROR: it broke" in render_text(checkpoint(error="it broke"), applied=True)


def test_write_report_produces_a_readable_and_a_machine_form(tmp_path):
    paths = write_report(checkpoint(audit_clean=True), applied=True, out_dir=tmp_path)

    assert paths["text"].read_text(encoding="utf-8").startswith("=")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["entity_rid"] == "ACCT-1"
    assert payload["totals"]["rows_deleted"] == 4


def test_a_report_filename_cannot_escape_the_output_directory(tmp_path):
    paths = write_report(
        checkpoint(entity_rid="../../etc/passwd"), applied=False, out_dir=tmp_path
    )
    assert paths["text"].parent == tmp_path
