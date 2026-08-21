"""
Purge one project fiscal year, with the financial recompute that must follow it.

Unlike the account, case and interaction purges, this one does not enumerate rows
and delete them. It runs the vendor's SECTION 1-8 SQL, which deletes *and*
recomputes the aggregates that survive the deletion. See
:mod:`trd365_data_purge.sections`.
"""

from __future__ import annotations

from pathlib import Path

#: The vendor's section files, moved here unchanged from
#: ``legacy/trd365_maintenance/data_purge/project_fiscal/base_sql``. They encode
#: both the foreign-key deletion order and the recompute arithmetic; they are data,
#: not code to rewrite.
BASE_SQL: Path = Path(__file__).parent / "base_sql"

#: One backup schema per database, shared by every section of a run.
BACKUP_SCHEMA = "data_purge"
