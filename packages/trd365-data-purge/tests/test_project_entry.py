"""
The two SECTION-driven entry points, end to end against fakes.

These are the only purges that do not go through the row-level engine, so nothing
in the shared CLI covers them. What is worth pinning is the wiring — which flags
exist, what a dry run says about itself, and the two places a partial failure has
to be explained rather than swallowed.
"""

from __future__ import annotations

import json

from fakes import AccountDirectory, FakeConnection, FakePool, table
from trd365_core.audit import MemoryAuditSink

from trd365_data_purge.project import __main__ as project
from trd365_data_purge.project_fiscal import __main__ as project_fiscal

ACCOUNT_RID = "ACCT-1"
R_NUMBER = "ACC-00042"
SCHEMA = "trd365_00042"
PROJECT_RID = "P001-project-1"
FISCAL_2025 = "P001-fiscal-2025"


# ---------------------------------------------------------------------------
# fakes: the section SQL is the vendor's, so the connection only records it
# ---------------------------------------------------------------------------


class Notices:
    def __init__(self, lines=()):
        self.lines = list(lines)

    def clear(self):
        pass

    def snapshot(self):
        return list(self.lines)

    @property
    def last(self):
        return self.lines[-1] if self.lines else None


class SectionsMixin:
    """
    Swallow the vendor DO blocks; let everything else reach the real fake.

    A mixin rather than a subclass because both the org connection and the account
    directory have to do this — section 3 runs on the main database, which is also
    the one that answers account resolution.
    """

    def _init_sections(self, fail_on=None):
        self.notices = Notices()
        self.sections: list[str] = []
        self.commits = 0
        self.fail_on = fail_on

    def cursor(self):
        outer = self
        inner = super().cursor()

        class Cursor:
            _section = False

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_exc):
                return False

            def close(self_inner):
                inner.close()

            def execute(self_inner, sql, params=None):
                if sql.lstrip().startswith("-- SECTION"):
                    self_inner._section = True
                    outer.sections.append(sql.splitlines()[0])
                    if outer.fail_on and sql.startswith(f"-- SECTION {outer.fail_on} "):
                        raise RuntimeError("relation does not exist")
                    return
                self_inner._section = False
                inner.execute(sql, params)

            @property
            def rowcount(self_inner):
                return inner.rowcount

            def fetchone(self_inner):
                return None if self_inner._section else inner.fetchone()

            def fetchall(self_inner):
                return [] if self_inner._section else inner.fetchall()

        return Cursor()

    def commit(self):
        self.commits += 1


class SectionConnection(SectionsMixin, FakeConnection):
    def __init__(self, tables=None, fail_on=None):
        super().__init__(tables or {})
        self._init_sections(fail_on)


class SectionDirectory(SectionsMixin, AccountDirectory):
    def __init__(self, accounts, fail_on=None):
        super().__init__(accounts)
        self._init_sections(fail_on)


def org(*years, fail_on=None, project_missing=False):
    tables = {
        (SCHEMA, "project_fiscal"): table(
            ["rid", "project_rid", "fiscal_year"],
            [
                {
                    "rid": FISCAL_2025 if y == 2025 else f"P001-fiscal-{y}",
                    "project_rid": PROJECT_RID,
                    "fiscal_year": y,
                }
                for y in years
            ],
        )
    }
    if not project_missing:
        tables[(SCHEMA, "project")] = table(
            ["rid", "account_rid"], [{"rid": PROJECT_RID, "account_rid": ACCOUNT_RID}]
        )
    return SectionConnection(tables, fail_on=fail_on)


def pool_for(org_conn):
    return FakePool(
        {
            "maindb": SectionDirectory(
                {ACCOUNT_RID: (R_NUMBER, "store_in_own", None)}, fail_on=org_conn.fail_on
            ),
            "orgdb": org_conn,
            "trd365ai": SectionConnection({}, fail_on=org_conn.fail_on),
        }
    )


def invoke(module, argv, org_conn, tmp_path, sink=None):
    pool = pool_for(org_conn)
    code = module.run(
        [*argv, "--out-dir", str(tmp_path / "reports"), "--heartbeat-seconds", "0"],
        pool_factory=lambda _env, log=None: pool,
        audit_sink=sink or MemoryAuditSink(),
    )
    return code, pool


def report_from(tmp_path):
    files = sorted((tmp_path / "reports").glob("*.json"))
    assert files, "no report was written"
    return json.loads(files[-1].read_text())


# ---------------------------------------------------------------------------
# one fiscal
# ---------------------------------------------------------------------------


class TestProjectFiscal:
    ARGV = ["--env", "dev", "--account-id", R_NUMBER, "--project-fiscal-rid", FISCAL_2025]

    def test_a_dry_run_runs_the_sections_and_keeps_nothing(self, tmp_path):
        conn = org(2023, 2025)
        code, pool = invoke(project_fiscal, self.ARGV, conn, tmp_path)
        assert code == 0
        assert len(conn.sections) == 3  # sections 1, 2, 4 are the org ones
        assert conn.commits == 0, "a dry run must not commit"

    def test_a_dry_run_says_it_is_not_free(self, tmp_path, capsys):
        # The whole reason this utility is different. An operator reading "dry run"
        # and assuming nothing happens would be wrong.
        invoke(project_fiscal, self.ARGV, org(2025), tmp_path)
        assert "not free" in capsys.readouterr().out

    def test_applying_commits(self, tmp_path):
        conn = org(2023, 2025)
        code, _ = invoke(project_fiscal, [*self.ARGV, "--apply", "--yes"], conn, tmp_path)
        assert code == 0
        assert conn.commits == 3

    def test_is_last_fiscal_is_reported_with_how_it_was_decided(self, tmp_path, capsys):
        invoke(project_fiscal, self.ARGV, org(2023, 2025), tmp_path)
        out = capsys.readouterr().out
        assert "last fiscal : False" in out
        assert "counted" in out
        assert "2 fiscal(s)" in out

    def test_forcing_last_fiscal_is_reported_as_forced(self, tmp_path, capsys):
        invoke(project_fiscal, [*self.ARGV, "--last-fiscal"], org(2023, 2025), tmp_path)
        out = capsys.readouterr().out
        assert "last fiscal : True" in out
        assert "forced" in out

    def test_a_missing_fiscal_exits_not_found(self, tmp_path):
        code, _ = invoke(project_fiscal, self.ARGV, org(2023), tmp_path)
        assert code == project_fiscal.EXIT_TARGET_NOT_FOUND

    def test_a_missing_account_exits_not_found(self, tmp_path):
        argv = ["--env", "dev", "--account-id", "ACC-99999", "--project-fiscal-rid", FISCAL_2025]
        code, _ = invoke(project_fiscal, argv, org(2025), tmp_path)
        assert code == project_fiscal.EXIT_TARGET_NOT_FOUND

    def test_selected_sections_only(self, tmp_path, capsys):
        conn = org(2025)
        invoke(project_fiscal, [*self.ARGV, "--sections", "4"], conn, tmp_path)
        assert [line.split("  ")[0] for line in conn.sections] == ["-- SECTION 4"]
        assert "sections    : 4 only" in capsys.readouterr().out

    def test_an_unknown_section_is_refused(self, tmp_path, capsys):
        code, _ = invoke(project_fiscal, [*self.ARGV, "--sections", "99"], org(2025), tmp_path)
        assert code == project_fiscal.EXIT_FAILED
        assert "no such section(s): 99" in capsys.readouterr().out

    def test_a_failure_names_the_last_section_that_committed(self, tmp_path, capsys):
        # Half-applied is the normal failure mode here, so the operator is told
        # where to resume rather than left to work it out from the log.
        conn = org(2025, fail_on=3)
        code, _ = invoke(project_fiscal, [*self.ARGV, "--apply", "--yes"], conn, tmp_path)
        assert code == project_fiscal.EXIT_FAILED
        out = capsys.readouterr().out
        assert "02_delete_project_ORGDB_SECTION2.sql was the last section to commit" in out
        assert "--sections from 3" in out

    def test_the_report_records_the_mode_and_the_sections(self, tmp_path):
        invoke(project_fiscal, [*self.ARGV, "--apply", "--yes"], org(2025), tmp_path)
        report = report_from(tmp_path)
        assert report["entity"] == "project_fiscal"
        assert report["mode"] == "apply"
        assert len(report["fiscals"]) == 1
        assert len(report["fiscals"][0]["sections"]) == 8

    def test_the_run_is_audited_even_when_it_fails(self, tmp_path):
        sink = MemoryAuditSink()
        invoke(
            project_fiscal, [*self.ARGV, "--apply", "--yes"], org(2025, fail_on=3), tmp_path, sink
        )
        assert len(sink.records) == 1
        record = sink.records[0]
        assert record.utility == "purge-project-fiscal"
        assert record.outcome == "failed"
        assert any("last committed section" in note for note in record.notes)


# ---------------------------------------------------------------------------
# a whole project
# ---------------------------------------------------------------------------


class TestProject:
    ARGV = ["--env", "dev", "--account-id", R_NUMBER, "--project", PROJECT_RID]

    def test_every_fiscal_runs_oldest_first(self, tmp_path, capsys):
        conn = org(2025, 2023, 2024)
        code, _ = invoke(project, self.ARGV, conn, tmp_path)
        assert code == 0
        out = capsys.readouterr().out
        assert "fiscals     : 3, oldest first" in out
        assert out.index("2023") < out.index("2024") < out.index("2025")

    def test_only_the_last_fiscal_is_marked(self, tmp_path, capsys):
        invoke(project, self.ARGV, org(2023, 2024, 2025), tmp_path)
        out = capsys.readouterr().out
        assert out.count("also deletes the project row") == 1
        # And it is the newest year that carries it.
        marked = [line for line in out.splitlines() if "also deletes" in line][0]
        assert "2025" in marked

    def test_a_project_can_be_named_by_its_code(self, tmp_path):
        conn = SectionConnection(
            {
                (SCHEMA, "project"): table(
                    ["rid", "account_rid", "project_code"],
                    [{"rid": PROJECT_RID, "account_rid": ACCOUNT_RID, "project_code": "FY25-1"}],
                ),
                (SCHEMA, "project_fiscal"): table(
                    ["rid", "project_rid", "fiscal_year"],
                    [{"rid": FISCAL_2025, "project_rid": PROJECT_RID, "fiscal_year": 2025}],
                ),
            }
        )
        argv = ["--env", "dev", "--account-id", R_NUMBER, "--project", "FY25-1"]
        code, _ = invoke(project, argv, conn, tmp_path)
        assert code == 0

    def test_a_project_with_no_fiscals_is_not_reported_as_purged(self, tmp_path, capsys):
        # The SECTION flow removes a project only as part of its last fiscal, so a
        # project with none cannot be deleted by it. Saying "done" would be a lie.
        code, _ = invoke(project, self.ARGV, org(), tmp_path)
        assert code == project.EXIT_FAILED
        assert "no fiscal years" in capsys.readouterr().out

    def test_an_unknown_project_exits_not_found(self, tmp_path):
        argv = ["--env", "dev", "--account-id", R_NUMBER, "--project", "nope"]
        code, _ = invoke(project, argv, org(2025), tmp_path)
        assert code == project.EXIT_TARGET_NOT_FOUND

    def test_it_stops_at_the_first_failing_fiscal(self, tmp_path, capsys):
        # A failed fiscal means the recompute chain is already inconsistent.
        conn = org(2023, 2024, 2025, fail_on=3)
        code, _ = invoke(project, [*self.ARGV, "--apply", "--yes"], conn, tmp_path)
        assert code == project.EXIT_FAILED
        assert "FAILED on fiscal 1 of 3" in capsys.readouterr().out

    def test_a_failure_says_how_to_resume(self, tmp_path, capsys):
        conn = org(2023, 2025, fail_on=3)
        invoke(project, [*self.ARGV, "--apply", "--yes"], conn, tmp_path)
        out = capsys.readouterr().out
        assert "Re-run purge-project-fiscal for" in out
        assert "--backup-schema data_purge" in out

    def test_the_report_covers_every_fiscal_attempted(self, tmp_path):
        invoke(project, [*self.ARGV, "--apply", "--yes"], org(2023, 2024, 2025), tmp_path)
        report = report_from(tmp_path)
        assert report["entity"] == "project"
        assert report["context"]["fiscals"] == 3
        assert len(report["fiscals"]) == 3


# ---------------------------------------------------------------------------
# what the registry says about them
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_both_declare_that_their_dry_run_is_not_free(self):
        from trd365_data_purge.registry import PURGE_PROJECT, PURGE_PROJECT_FISCAL

        assert PURGE_PROJECT_FISCAL.dry_run_executes is True
        assert PURGE_PROJECT.dry_run_executes is True

    def test_the_row_level_purges_do_not(self):
        from trd365_data_purge.registry import PURGE_ACCOUNT, PURGE_CASE, PURGE_INTERACTION

        for utility in (PURGE_ACCOUNT, PURGE_CASE, PURGE_INTERACTION):
            assert utility.dry_run_executes is False, utility.id

    def test_they_do_not_advertise_flags_they_do_not_have(self):
        # chunk size, checkpoints and the model snapshot belong to the row-level
        # engine. Offering them here would generate a form field that does nothing.
        from trd365_data_purge.registry import PURGE_PROJECT

        names = {p.name for p in PURGE_PROJECT.parameters}
        assert not names & {"chunk_size", "restart", "model_max_age_days", "ignore_model"}

    def test_every_registered_utility_is_importable(self):
        # The registry names a module string; a typo there is only found at run time.
        import importlib

        from trd365_core.registry import load_installed_utilities, registry

        load_installed_utilities()
        for utility in registry.all():
            importlib.import_module(utility.module)
