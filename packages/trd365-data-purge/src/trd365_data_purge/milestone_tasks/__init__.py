"""
Delete the tasks under one milestone of one case, leaving the milestone itself.

This was 18 KB of hand-written SQL with no way to run it —
``legacy/trd365_maintenance/task_deletion_by_milestone/base_sql/base_sql.sql``,
whose instructions were "edit three variables at the top and run it in psql".
Nothing invoked it, nothing recorded that it had been run, and it shipped with a
real tenant schema and a real case rid in those three variables.

It needed a runner rather than a rewrite, and :mod:`trd365_data_purge.sections`
already is one, so the SQL moves here unchanged (renamed only, so the runner can
tell which database it belongs to) and gets driven properly: the identifiers
substituted and checked, the run audited, a report written.

**Its dry run is a real dry run.** Unlike the project sections, this script has a
``dry_run`` flag of its own and honours it — counting rows and skipping every
delete. So this utility previews without doing the work, and ``dry_run_executes``
is false.
"""

from __future__ import annotations

from pathlib import Path

from .. import sections as S

#: The vendor's script, moved unchanged.
BASE_SQL: Path = Path(__file__).parent / "base_sql"

#: This family's declarations. ``v_schema`` rather than the project family's
#: ``v_schema_name``: the two scripts were written by different hands and this is
#: exactly why the variable sets are per-family.
VARIABLES = S.Variables(
    text={
        "v_schema": "schema",
        "v_case_rid": "case_rid",
        "v_milestone_rid": "milestone_rid",
    },
    # The script's own preview switch. Driven from --apply, so "dry run" here
    # means what it means everywhere else in this package: nothing is deleted.
    boolean={"dry_run": "dry_run"},
)
