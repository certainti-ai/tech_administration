#!/usr/bin/env python3
"""Profile which response-date field is populated, across all org schemas."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engine import db  # noqa: E402
from correct import _fetch  # noqa: E402
from psycopg2 import sql  # noqa: E402


def main():
    pool = db.ConnectionPool(db.load_config(HERE / "config" / "db_config.json"))
    try:
        schemas = [r[0] for r in _fetch(pool, "orgdb",
            "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'trd365\\_%' ESCAPE '\\' "
            "AND nspname NOT LIKE '%backup%' ORDER BY 1")]
        tot = dict(rows=0, sent=0, resp_updated=0, resp_submitted=0,
                   accts=set(), sh_rows=0, sh_recv=0, sh_recv_dt=0)
        for S in schemas:
            r = _fetch(pool, "orgdb", sql.SQL(
                "SELECT count(*), count(sent_on_datetime), count(response_updated_on), "
                "count(NULLIF(response_submitted_on,'')), count(DISTINCT account_rid), "
                "min(response_updated_on), max(response_updated_on) "
                "FROM {}.interactions WHERE COALESCE(is_deleted,false)=false").format(sql.Identifier(S)))[0]
            sh = _fetch(pool, "orgdb", sql.SQL(
                "SELECT count(*), count(*) FILTER (WHERE response_received), "
                "count(response_received_datetime) FROM {}.interaction_send_history"
                ).format(sql.Identifier(S)))[0]
            tot["rows"] += r[0]; tot["sent"] += r[1]; tot["resp_updated"] += r[2]
            tot["resp_submitted"] += r[3]
            tot["sh_rows"] += sh[0]; tot["sh_recv"] += sh[1]; tot["sh_recv_dt"] += sh[2]
            print(f"{S}: interactions={r[0]:>5} sent={r[1]:>5} resp_updated={r[2]:>5} "
                  f"resp_submitted={r[3]:>5} accts={r[4]:>3} | send_hist={sh[0]:>4} "
                  f"recv={sh[1]:>4} recv_dt={sh[2]:>4} | resp_updated range {r[5]}..{r[6]}")
        print("\nTOTALS across", len(schemas), "schemas:")
        for k in ("rows", "sent", "resp_updated", "resp_submitted", "sh_rows", "sh_recv", "sh_recv_dt"):
            print(f"  {k:<16} {tot[k]}")
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
