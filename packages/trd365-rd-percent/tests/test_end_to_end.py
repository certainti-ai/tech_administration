"""
The whole utility, driven through its real CLI against a fake pair of databases.

What is worth pinning: which statements run and which do not, that a snapshot
precedes every overwrite, that the two databases are separate transactions, and
that the one unrecoverable failure mode is described accurately rather than
reported as a rollback that did not happen.
"""

from __future__ import annotations

import json

import fakes
from trd365_core.audit import MemoryAuditSink

from trd365_rd_percent import __main__ as cli

ARGV = [
    "--env", "dev",
    "--account-id", fakes.R_NUMBER,
    "--project-code", "FY25 Project 1",
    "--fiscal-year", "2025",
    "--potential-ai", "60",
    "--adjustment", "5",
    "--final", "65",
]


def invoke(tmp_path, extra=(), *, main=None, org=None, sink=None):
    main = main if main is not None else fakes.main_connection()
    org = org if org is not None else fakes.org_connection()
    pool = fakes.Pool(main, org)
    code = cli.run(
        [*ARGV, "--out-dir", str(tmp_path / "reports"), *extra],
        pool_factory=lambda _env, log=None: pool,
        audit_sink=sink or MemoryAuditSink(),
    )
    return code, main, org


def report(tmp_path):
    files = sorted((tmp_path / "reports").glob("*.json"))
    assert files, "no report written"
    return json.loads(files[-1].read_text())


class TestDryRun:
    def test_it_writes_nothing(self, tmp_path):
        code, main, org = invoke(tmp_path)
        assert code == 0
        assert org.did_not_run("UPDATE")
        assert org.did_not_run("INSERT INTO")
        assert org.commits == 0
        assert main.commits == 0

    def test_a_dry_run_here_is_genuinely_free(self, tmp_path, capsys):
        # Unlike the project purges, this one previews without executing anything.
        invoke(tmp_path)
        out = capsys.readouterr().out
        assert "DRY RUN — nothing was written" in out

    def test_it_still_reports_every_figure(self, tmp_path):
        invoke(tmp_path)
        computed = report(tmp_path)["computed"]
        assert computed["rd_percent_final"] == 65.0
        # 50_000 * 0.65 * 0.65
        assert computed["qre_subcon"] == 50_000.0 * 0.65 * 0.65
        assert computed["qre_final"] == (
            100_000 * 0.65 + 50_000 * 0.65 * 0.65 + 20_000 * 0.65
        )

    def test_the_sub_con_cap_is_reported_with_its_reason(self, tmp_path, capsys):
        invoke(tmp_path)
        assert "sub-con cap : 65.0%  (configured)" in capsys.readouterr().out


class TestApply:
    def test_every_expected_table_is_written(self, tmp_path):
        code, main, org = invoke(tmp_path, ["--apply", "--yes"])
        assert code == 0
        for table in (
            "project_fiscal",
            "project_resource_fiscal",
            "case_projects",
            "case_project_resource_fiscal",
            "project_timeline",
            "project_qre_adjustment_history",
        ):
            assert org.ran(table), table
        assert main.ran("project_fiscal_summary")

    def test_each_update_is_preceded_by_its_own_snapshot(self, tmp_path):
        # The property that makes this reversible. A snapshot after the update
        # would capture the new values and be worthless.
        _, _, org = invoke(tmp_path, ["--apply", "--yes"])
        for table in ("project_fiscal", "project_resource_fiscal"):
            snapshot_at = next(
                i
                for i, (sql, params) in enumerate(org.statements)
                if "to_jsonb(t)" in sql and table in params
            )
            update_at = next(
                i
                for i, (sql, _) in enumerate(org.statements)
                if sql.startswith(f'UPDATE "trd365_00042"."{table}" SET')
            )
            assert snapshot_at < update_at, (
                f"{table}: the snapshot must run before the update, or it captures "
                f"the new values and is worthless"
            )

    def test_the_snapshot_filter_matches_the_update_filter(self, tmp_path):
        # case_projects is the one that could differ: both must carry the
        # non-closed-case join, or the backup covers rows that never changed.
        _, _, org = invoke(tmp_path, ["--apply", "--yes"])
        snapshots = [s for s, _ in org.statements if "to_jsonb(cp)" in s]
        assert snapshots, "no case_projects snapshot"
        assert "c.status_rid <> %s" in snapshots[0]

    def test_the_two_databases_commit_separately(self, tmp_path):
        # Separate servers: nothing can span them, and the application does not try.
        _, main, org = invoke(tmp_path, ["--apply", "--yes"])
        assert org.commits >= 1
        assert main.commits >= 1

    def test_the_computed_figures_reach_the_statements(self, tmp_path):
        _, _, org = invoke(tmp_path, ["--apply", "--yes"])
        statement, params = org.ran('UPDATE "trd365_00042"."project_fiscal" SET')[0]
        # potential_ai, adjustment, net, final, fte, subcon, nonlabor, ...
        assert params[0] == 60.0
        assert params[1] == 5.0
        assert params[2] == 65.0
        assert params[5] == 50_000.0 * 0.65 * 0.65

    def test_the_history_row_stores_the_delta_not_the_final(self, tmp_path):
        # The application's field naming: rd_percent_adjustment is the delta.
        _, _, org = invoke(tmp_path, ["--apply", "--yes"])
        _, params = org.ran("project_qre_adjustment_history")[0]
        assert 5.0 in params
        assert 65.0 not in params

    def test_the_audit_record_carries_the_cap_and_the_backup_id(self, tmp_path):
        sink = MemoryAuditSink()
        invoke(tmp_path, ["--apply", "--yes"], sink=sink)
        assert len(sink.records) == 1
        notes = " ".join(sink.records[0].notes)
        assert "sub-con cap 65.0%" in notes
        assert "backup run id" in notes

    def test_rows_affected_is_recorded_per_table(self, tmp_path):
        sink = MemoryAuditSink()
        invoke(tmp_path, ["--apply", "--yes"], sink=sink)
        affected = sink.records[0].rows_affected
        assert any(key.endswith("project_fiscal") for key in affected)


class TestClosedCases:
    """Closed-case financials are frozen. Two separate rules protect them."""

    def test_a_project_mapped_to_a_closed_case_skips_the_resource_table(self, tmp_path):
        org = fakes.org_connection(mapped_to_closed=True)
        code, _, org = invoke(tmp_path, ["--apply", "--yes"], org=org)
        assert code == 0
        assert org.did_not_run('UPDATE "trd365_00042"."case_project_resource_fiscal"')

    def test_case_projects_is_still_updated_for_non_closed_cases(self, tmp_path):
        # All-or-nothing applies to the resource table only; case_projects filters
        # per row.
        org = fakes.org_connection(mapped_to_closed=True)
        _, _, org = invoke(tmp_path, ["--apply", "--yes"], org=org)
        assert org.ran('UPDATE "trd365_00042"."case_projects"')

    def test_a_schema_without_the_cases_table_skips_the_case_module(self, tmp_path):
        org = fakes.org_connection(has_cases=False)
        code, _, org = invoke(tmp_path, ["--apply", "--yes"], org=org)
        assert code == 0
        assert org.did_not_run('UPDATE "trd365_00042"."case_projects"')

    def test_without_a_closed_status_the_case_module_is_left_alone(self, tmp_path, capsys):
        # Not "update everything": without the status there is no way to tell a
        # closed case from an open one, and guessing would rewrite frozen figures.
        main = fakes.main_connection(closed_status=None)
        code, _, org = invoke(tmp_path, ["--apply", "--yes"], main=main)
        assert code == 0
        assert org.did_not_run('UPDATE "trd365_00042"."case_projects"')
        assert "no closed case status" in capsys.readouterr().out


class TestRefusals:
    def test_inconsistent_percentages_are_refused_before_any_database_is_touched(self, tmp_path):
        main = fakes.main_connection()
        org = fakes.org_connection()
        pool = fakes.Pool(main, org)
        code = cli.run(
            [*ARGV[:-1], "70", "--out-dir", str(tmp_path / "r"), "--apply", "--yes"],
            pool_factory=lambda _env, log=None: pool,
            audit_sink=MemoryAuditSink(),
        )
        assert code == cli.EXIT_FAILED
        assert main.statements == [], "it should not have connected at all"

    def test_an_unknown_account_exits_not_found(self, tmp_path):
        main = fakes.Connection(
            answers=[(r"account.*r_number", (["rid", "r_number", "fiscal_start_date",
                                              "fiscal_end_date"], []))]
        )
        code, _, _ = invoke(tmp_path, main=main)
        assert code == cli.EXIT_TARGET_NOT_FOUND

    def test_an_ambiguous_project_code_is_refused(self, tmp_path, capsys):
        # Two rows match. Correcting the first would rewrite money on a row nobody
        # named.
        org = fakes.org_connection(
            fiscal_rows=[fakes.project_fiscal_row(), fakes.project_fiscal_row()]
        )
        code, _, _ = invoke(tmp_path, org=org)
        assert code == cli.EXIT_TARGET_NOT_FOUND
        assert "2 project_fiscal rows match" in capsys.readouterr().out

    def test_a_missing_schema_is_refused(self, tmp_path):
        org = fakes.org_connection(schema_exists=False)
        code, _, _ = invoke(tmp_path, org=org)
        assert code == cli.EXIT_TARGET_NOT_FOUND


class TestPartialFailure:
    def test_an_org_failure_rolls_back_and_leaves_main_untouched(self, tmp_path):
        org = fakes.org_connection(fail_on='UPDATE "trd365_00042"."project_resource_fiscal"')
        code, main, org = invoke(tmp_path, ["--apply", "--yes"], org=org)
        assert code == cli.EXIT_FAILED
        assert org.rollbacks >= 1
        assert main.did_not_run("project_fiscal_summary SET")

    def test_the_snapshot_table_survives_a_rolled_back_record(self, tmp_path):
        # The one commit that is deliberately outside the record's transaction.
        # Without it, the first record to fail would also discard the table its
        # own backup rows were meant to live in, and the next record would have
        # to create it again.
        org = fakes.org_connection(fail_on='UPDATE "trd365_00042"."project_resource_fiscal"')
        _, _, org = invoke(tmp_path, ["--apply", "--yes"], org=org)
        assert org.ran("CREATE TABLE IF NOT EXISTS")
        assert org.commits >= 1, "the DDL commit is separate from the record"
        assert org.rollbacks >= 1, "and the record itself still rolled back"

    def test_a_main_failure_says_the_org_side_is_already_committed(self, tmp_path, capsys):
        # The one unrecoverable case, and the reason to be precise: two servers,
        # no distributed transaction, and the application has the same hole. An
        # operator must not read "rolled back" and think nothing happened.
        main = fakes.main_connection(fail_on="UPDATE")
        code, main, org = invoke(tmp_path, ["--apply", "--yes"], main=main)
        assert code == cli.EXIT_FAILED
        assert org.commits >= 1
        out = capsys.readouterr().out
        assert "org database changes ARE committed" in out
        assert "idempotent" in out

    def test_that_case_is_recorded_in_the_audit_trail(self, tmp_path):
        sink = MemoryAuditSink()
        main = fakes.main_connection(fail_on="UPDATE")
        invoke(tmp_path, ["--apply", "--yes"], main=main, sink=sink)
        record = sink.records[0]
        assert record.outcome == "failed"
        assert any("org database committed" in note for note in record.notes)


class TestRegistration:
    def test_it_supersedes_the_legacy_tool(self):
        from trd365_rd_percent.registry import RD_PERCENT_UPDATE

        assert RD_PERCENT_UPDATE.supersedes == "manual-rd-percent-update"

    def test_its_dry_run_is_free(self):
        # Unlike the project purges. The distinction is now explicit in the
        # registry, so the console can say which is which.
        from trd365_rd_percent.registry import RD_PERCENT_UPDATE

        assert RD_PERCENT_UPDATE.dry_run_executes is False

    def test_the_notes_warn_about_the_legacy_sub_con_defect(self):
        # Anyone comparing this tool's output to the old one's will see different
        # sub-contractor figures and needs to know which is right.
        from trd365_rd_percent.registry import RD_PERCENT_UPDATE

        assert "cap" in RD_PERCENT_UPDATE.notes
        assert "overstated" in RD_PERCENT_UPDATE.notes
