# -*- coding: utf-8 -*-
"""Snapshot interactions performance out of trd365_all. Read-only.

Feeds the interactions panel of the platform metrics dashboard: one row per
account and fiscal year, a monthly send/response series behind the run-rate
chart, and the per-year response latencies, which do not add up from the
account rows and so are read at their own grain.

Test and release accounts are excluded on the matview's own is_test_account
flag rather than on an account-name pattern: the flag catches two accounts
('WIPRO UK Test', 'Release-v6.0.5-US') that no sensible ILIKE would.

Every counter but `held` is scoped to the rows that were actually sent, so
each share on the dashboard has the same denominator and none can exceed it.

    python tools/extract_interaction_metrics.py [out.json]

Runs on the maintenance VM, where trd365_core resolves credentials from Key
Vault; no Claude Code session has a network path to these databases.
"""
import json, datetime, decimal, sys

from trd365_core.environments import Environment
from trd365_core.db import ConnectionPool

SENT = "i.sent_on_datetime IS NOT NULL"
BASE = "coalesce(i.is_deleted,false)=false AND coalesce(i.is_test_account,false)=false"
# response_submitted_on is varchar(50) in the matview, so every use is cast.
RESP = "i.response_submitted_on::timestamptz"
LAG = "EXTRACT(epoch FROM (%s - i.sent_on_datetime))/86400.0" % RESP
AGE = "EXTRACT(epoch FROM (now() - i.sent_on_datetime))/86400.0"

ROWS = """
SELECT i.account_name, i.fiscal_year,
       count(*)                                                        AS held,
       count(*) FILTER (WHERE SENT)                                     AS sent,
       count(*) FILTER (WHERE i.response_submitted_on IS NOT NULL)      AS responded,
       count(*) FILTER (WHERE SENT AND i.last_reminder_on IS NOT NULL)  AS reminded,
       count(*) FILTER (WHERE SENT AND i.is_chat_interaction)           AS chat,
       count(*) FILTER (WHERE SENT AND i.interaction_source_name = 'Auto')   AS auto,
       count(*) FILTER (WHERE SENT AND i.interaction_source_name = 'Manual') AS manual,
       count(*) FILTER (WHERE SENT AND i.is_ai_processed)               AS ai,
       count(DISTINCT i.project_rid) FILTER (WHERE SENT)                AS projects,
       count(DISTINCT lower(i.recipient_email)) FILTER (WHERE SENT)     AS recipients,
       min(i.sent_on_datetime)::date::text                              AS first_sent,
       max(i.sent_on_datetime)::date::text                              AS last_sent,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY {lag})::numeric, 1) AS med_days,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY {lag})::numeric, 1) AS p90_days,
       count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL
             AND i.response_submitted_on IS NULL AND {age} <= 14)       AS p14,
       count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL
             AND i.response_submitted_on IS NULL AND {age} > 14 AND {age} <= 30) AS p30,
       count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL
             AND i.response_submitted_on IS NULL AND {age} > 30 AND {age} <= 60) AS p60,
       count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL
             AND i.response_submitted_on IS NULL AND {age} > 60)        AS p60p
FROM trd365_all.interactions i
WHERE {base} AND i.account_name IS NOT NULL
GROUP BY 1, 2
HAVING count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL) > 0
ORDER BY 1, 2
""".format(base=BASE, lag=LAG, age=AGE).replace("SENT", SENT)

# One series row per account / fiscal year / calendar month. Sends are counted
# in the month they went out, responses in the month they came back, so the two
# lines are not a cohort pair and the page says as much.
SERIES = """
SELECT account_name, fiscal_year, m, sum(sent) AS sent, sum(resp) AS resp
FROM (
  SELECT i.account_name, i.fiscal_year,
         to_char(date_trunc('month', i.sent_on_datetime), 'YYYY-MM') AS m,
         1 AS sent, 0 AS resp
  FROM trd365_all.interactions i
  WHERE {base} AND i.sent_on_datetime IS NOT NULL AND i.account_name IS NOT NULL
  UNION ALL
  SELECT i.account_name, i.fiscal_year,
         to_char(date_trunc('month', {resp}), 'YYYY-MM') AS m,
         0, 1
  FROM trd365_all.interactions i
  WHERE {base} AND i.response_submitted_on IS NOT NULL AND i.account_name IS NOT NULL
) s
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
""".format(base=BASE, resp=RESP)

# Fiscal-year medians cannot be summed up from the account rows, so they are
# read at fiscal-year grain as well.
FY = """
SELECT i.fiscal_year,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY {lag})::numeric, 1) AS med_days,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY {lag})::numeric, 1) AS p90_days,
       count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL AND {age} <= 30) AS sent_30d
FROM trd365_all.interactions i
WHERE {base}
GROUP BY 1 ORDER BY 1
""".format(base=BASE, lag=LAG, age=AGE)

EXCLUDED = """
SELECT count(DISTINCT i.account_name), count(*),
       count(*) FILTER (WHERE i.sent_on_datetime IS NOT NULL)
FROM trd365_all.interactions i
WHERE coalesce(i.is_deleted,false)=false AND i.is_test_account IS TRUE
"""

ROW_KEYS = ["account","fy","held","sent","responded","reminded","chat","auto","manual","ai",
            "projects","recipients","first_sent","last_sent","med_days","p90_days",
            "p14","p30","p60","p60p"]


def j(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    return o


def main():
    with ConnectionPool(Environment.PROD) as pool:
        rows = [dict(zip(ROW_KEYS, [j(v) for v in r])) for r in pool.fetch("orgdb", ROWS)]
        series = [{"account": r[0], "fy": r[1], "m": r[2], "sent": int(r[3]), "resp": int(r[4])}
                  for r in pool.fetch("orgdb", SERIES)]
        fy = {str(r[0]): {"med_days": j(r[1]), "p90_days": j(r[2]), "sent_30d": int(r[3])}
              for r in pool.fetch("orgdb", FY)}
        ex = pool.fetch("orgdb", EXCLUDED)[0]

    out = {
        "generated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat(),
        "rows": rows,
        "series": series,
        "fy_latency": fy,
        "excluded": {"accounts": int(ex[0]), "interactions": int(ex[1]), "sent": int(ex[2])},
    }
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/trd365/work/ix2.json"
    with open(out_path, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print("rows=%d series=%d fy=%d excluded_accounts=%d excluded_sent=%d"
          % (len(rows), len(series), len(fy), ex[0], ex[2]))
    print("sent=%d responded=%d" % (sum(r["sent"] for r in rows),
                                    sum(r["responded"] for r in rows)))


main()
