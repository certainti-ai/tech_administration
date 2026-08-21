"""
Running the SECTION flow for one fiscal.

The behaviour under test is almost entirely about failure and about
transactions — what commits, what does not, and what the caller is told
afterwards. The SQL itself is the vendor's and is not exercised here; a fake
connection records what it was asked to run.
"""

from __future__ import annotations

from trd365_data_purge import sections as S
from trd365_data_purge.project_fiscal import BACKUP_SCHEMA, BASE_SQL, flow

PARAMS = {
    "schema_name": "trd365_00042",
    "account_rid": "P001-account-1",
    "project_rid": "P001-project-1",
    "project_fiscal_id": "P001-fiscal-2025",
    "fiscal_year": 2025,
    "is_last_fiscal": False,
}


class Notices:
    """psycopg2's connection.notices, as this code uses it."""

    def __init__(self, lines=()):
        self.lines = list(lines)

    def clear(self):
        pass

    def snapshot(self):
        return list(self.lines)

    @property
    def last(self):
        return self.lines[-1] if self.lines else None


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        # Anchored on the file's first line. Matching anywhere in the text picks up
        # the cross-references the sections make to each other — section 2's header
        # mentions section 3 — and fails the wrong one.
        if self.conn.fail_on and sql.startswith(f"-- SECTION {self.conn.fail_on} "):
            raise RuntimeError("relation does not exist")

    def close(self):
        pass


class Connection:
    def __init__(self, notices=(), fail_on=None):
        self.notices = Notices(notices)
        self.executed: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on = fail_on

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class Pool:
    def __init__(self, **connections):
        self.connections = connections

    def get(self, db_key):
        return self.connections.setdefault(db_key, Connection())


def pool(fail_on=None, notices=()):
    return Pool(
        orgdb=Connection(notices=notices, fail_on=fail_on),
        maindb=Connection(notices=notices, fail_on=fail_on),
        trd365ai=Connection(notices=notices, fail_on=fail_on),
    )


def run(p, *, dry_run, log=None, **kwargs):
    return flow.run_fiscal(
        p,
        S.discover(BASE_SQL),
        PARAMS,
        backup_schema=BACKUP_SCHEMA,
        dry_run=dry_run,
        log=log or (lambda _m: None),
        heartbeat_seconds=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_applying_commits_each_section_as_it_succeeds(self):
        # The sections depend on each other's committed state — section 2 reads the
        # backup schema section 1 created — so this is per-section, not one big
        # transaction at the end.
        p = pool()
        outcome = run(p, dry_run=False)
        assert outcome.status == "ok"
        assert p.get("orgdb").commits == 3  # sections 1, 2, 4
        assert p.get("maindb").commits == 2  # sections 3, 5
        assert p.get("trd365ai").commits == 3  # sections 6, 7, 8

    def test_a_dry_run_commits_nothing_and_rolls_everything_back(self):
        # Note what this means: the deletes and the recompute *did* run, inside
        # transactions that are then discarded. It is the only way to dry-run SQL
        # that recomputes.
        p = pool()
        outcome = run(p, dry_run=True)
        assert outcome.status == "ok"
        for db in ("orgdb", "maindb", "trd365ai"):
            assert p.get(db).commits == 0, db
            assert p.get(db).rollbacks >= 1, db

    def test_a_dry_run_rolls_back_every_database_it_touched(self):
        p = pool()
        run(p, dry_run=True)
        assert {db for db in ("orgdb", "maindb", "trd365ai") if p.get(db).rollbacks} == {
            "orgdb",
            "maindb",
            "trd365ai",
        }

    def test_a_dry_run_still_rolls_back_after_a_failure(self):
        p = pool(fail_on=3)
        outcome = run(p, dry_run=True)
        assert outcome.status == "error"
        assert p.get("orgdb").rollbacks >= 1
        assert p.get("maindb").rollbacks >= 1

    def test_a_failed_rollback_does_not_hide_the_result(self):
        class Stubborn(Connection):
            def rollback(self):
                raise RuntimeError("connection already closed")

        p = Pool(orgdb=Stubborn(), maindb=Stubborn(), trd365ai=Stubborn())
        warnings: list[str] = []
        outcome = run(p, dry_run=True, log=warnings.append)
        assert outcome.status == "ok"
        assert any("could not roll back" in line for line in warnings)


# ---------------------------------------------------------------------------
# failure
# ---------------------------------------------------------------------------


class TestFailure:
    def test_a_failing_section_stops_the_run(self):
        outcome = run(pool(fail_on=3), dry_run=False)
        assert outcome.status == "error"
        assert outcome.error.startswith("03_delete_project_MAINDB_SECTION3.sql")
        assert [s.status for s in outcome.sections] == ["ok", "ok", "error"]

    def test_the_furthest_committed_section_is_reported_by_name(self):
        # The half-applied case. These sections commit as they go, so a failure at
        # section 3 leaves 1 and 2 applied. A resumed run has to know which, and
        # "the run failed" alone does not say.
        outcome = run(pool(fail_on=3), dry_run=False)
        assert outcome.last_committed is not None
        assert outcome.last_committed.number == 2
        assert outcome.to_dict()["last_committed_section"] == (
            "02_delete_project_ORGDB_SECTION2.sql"
        )

    def test_a_dry_run_has_nothing_committed_to_report(self):
        outcome = run(pool(fail_on=3), dry_run=True)
        assert outcome.last_committed is None
        assert outcome.to_dict()["last_committed_section"] is None

    def test_sql_that_would_not_be_safe_is_refused_before_it_runs(self):
        # prepare() rejecting a section must stop the flow, not be retried or
        # skipped: the reason it rejected is that the SQL still names somebody
        # else's data.
        p = pool()
        outcome = flow.run_fiscal(
            p,
            S.discover(BASE_SQL),
            {**PARAMS, "account_rid": ""},
            backup_schema=BACKUP_SCHEMA,
            dry_run=False,
            log=lambda _m: None,
            heartbeat_seconds=0,
        )
        assert outcome.status == "error"
        assert outcome.sections[0].status == "refused"
        assert p.get("orgdb").executed == []
        assert p.get("orgdb").commits == 0


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


class TestReporting:
    def test_the_sections_run_in_order_on_the_right_databases(self):
        outcome = run(pool(), dry_run=False)
        assert [s.number for s in outcome.sections] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert [s.db_key for s in outcome.sections] == [
            "orgdb",
            "orgdb",
            "maindb",
            "orgdb",
            "maindb",
            "trd365ai",
            "trd365ai",
            "trd365ai",
        ]

    def test_the_interesting_notices_are_surfaced_without_verbose(self):
        lines: list[str] = []
        run(
            pool(notices=["NOTICE: deleted project_task: 14", "NOTICE: nothing to see"]),
            dry_run=False,
            log=lines.append,
        )
        shown = " ".join(lines)
        assert "deleted project_task: 14" in shown
        assert "nothing to see" not in shown

    def test_verbose_surfaces_everything(self):
        lines: list[str] = []
        run(pool(notices=["NOTICE: nothing to see"]), dry_run=False, log=lines.append, verbose=True)
        assert any("nothing to see" in line for line in lines)

    def test_the_outcome_records_what_it_was_asked_to_do(self):
        payload = run(pool(), dry_run=False).to_dict()
        assert payload["project_fiscal_id"] == PARAMS["project_fiscal_id"]
        assert payload["fiscal_year"] == 2025
        assert payload["is_last_fiscal"] is False
        assert payload["backup_schema"] == BACKUP_SCHEMA
        assert len(payload["sections"]) == 8

    def test_is_last_fiscal_is_normalised_in_the_record(self):
        # It arrives from a CSV or a flag as any of several spellings; the report
        # has to say which it actually was.
        p = pool()
        outcome = flow.run_fiscal(
            p,
            S.discover(BASE_SQL),
            {**PARAMS, "is_last_fiscal": "TRUE"},
            backup_schema=BACKUP_SCHEMA,
            dry_run=True,
            log=lambda _m: None,
            heartbeat_seconds=0,
        )
        assert outcome.is_last_fiscal is True
