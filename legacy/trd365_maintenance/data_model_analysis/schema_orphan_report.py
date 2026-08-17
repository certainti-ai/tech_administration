#!/usr/bin/env python3
"""Detailed orphan analysis for ONE org tenant schema, across BOTH databases.

ORG side  — child rows in <schema> whose {entity}_rid points at a missing parent
            (same-schema parents; account_rid vs main.trd365.account). Global-
            lookup entities (empty per-tenant table + a master in main) are
            auto-excluded to avoid false positives (e.g. interaction_type).

MAIN side — rows in main.trd365 tables that BELONG to this schema's account(s)
            but reference org entities (project/project_fiscal/case) that no
            longer exist in <schema>, or an account no longer in main.account.
            "Belongs to this schema" = main.account_rid is one of the accounts
            whose data lives in <schema> (distinct account_rid found in the
            schema's project/account_fiscal tables).

Cross-DB checks are done by loading the parent rid sets into Python.

Usage:
    python schema_orphan_report.py --schema trd365_00416 --sample 3
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db  # noqa: E402
from model_analysis import catalog, resolve_parent, _fetch, BACKUP_TABLE_RE  # noqa: E402
from psycopg2 import sql as S_  # noqa: E402

ORG_ENTITY_COLS = ["project_rid", "project_fiscal_rid", "case_rid", "account_rid"]


def rid_set(pool, dbk, schema, table):
    try:
        return {r[0] for r in _fetch(pool, dbk, S_.SQL("SELECT rid FROM {}.{}").format(
            S_.Identifier(schema), S_.Identifier(table)))}
    except Exception:
        return set()


def org_side(pool, S, main_schema, acct_valid, sample, log):
    cat = catalog(pool, "orgdb", S)
    rid_tables = {t for t, d in cat.items() if d["has_rid"]}
    # global-lookup exclusion: parent empty per-tenant + master exists in main
    parents = set()
    for t, d in cat.items():
        for col in d["rid_cols"]:
            if col != "account_rid":
                p, _ = resolve_parent(col, rid_tables)
                if p:
                    parents.add(p)
    global_excl = set()
    for p in parents:
        cnt = _fetch(pool, "orgdb", S_.SQL("SELECT count(*) FROM {s}.{t}").format(
            s=S_.Identifier(S), t=S_.Identifier(p)))[0][0]
        if cnt == 0 and _fetch(pool, "maindb",
                "SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name='rid'",
                [main_schema, p]):
            global_excl.add(p)
    if global_excl:
        log(f"  (org: excluding global-lookup entities {sorted(global_excl)})")

    results = []
    for t, d in sorted(cat.items()):
        if BACKUP_TABLE_RE.search(t):
            continue
        for col in d["rid_cols"]:
            if col == "account_rid":
                rows = _fetch(pool, "orgdb", S_.SQL(
                    "SELECT {c}, count(*) FROM {s}.{t} WHERE {c} IS NOT NULL GROUP BY {c}"
                ).format(c=S_.Identifier(col), s=S_.Identifier(S), t=S_.Identifier(t)))
                bad = [(v, n) for v, n in rows if v not in acct_valid]
                cnt = sum(n for _, n in bad)
                samp = [v for v, _ in bad][:sample]
                ent, ptbl = "account", "main.account"
            else:
                ptbl, _ = resolve_parent(col, rid_tables)
                if not ptbl or ptbl in global_excl:
                    continue
                cnt = _fetch(pool, "orgdb", S_.SQL(
                    "SELECT count(*) FROM {s}.{t} c WHERE c.{col} IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM {s}.{pt} p WHERE p.rid=c.{col})"
                ).format(s=S_.Identifier(S), t=S_.Identifier(t), col=S_.Identifier(col), pt=S_.Identifier(ptbl)))[0][0]
                samp = []
                if cnt and sample:
                    samp = [r[0] for r in _fetch(pool, "orgdb", S_.SQL(
                        "SELECT DISTINCT c.{col} FROM {s}.{t} c WHERE c.{col} IS NOT NULL "
                        "AND NOT EXISTS (SELECT 1 FROM {s}.{pt} p WHERE p.rid=c.{col}) LIMIT %s"
                    ).format(s=S_.Identifier(S), t=S_.Identifier(t), col=S_.Identifier(col), pt=S_.Identifier(ptbl)), [sample])]
                ent = {"project": "project", "resources": "resource", "cases": "case"}.get(ptbl, ptbl)
            if cnt:
                results.append({"side": "ORG", "table": t, "column": col, "entity": ent,
                                "orphans": cnt, "samples": "; ".join(str(x) for x in samp)})
    return results


def main_side(pool, S, main_schema, acct_valid, sample, log):
    # org entity rid sets for THIS schema
    org_sets = {"project_rid": rid_set(pool, "orgdb", S, "project"),
                "project_fiscal_rid": rid_set(pool, "orgdb", S, "project_fiscal"),
                "case_rid": rid_set(pool, "orgdb", S, "cases"),
                "account_rid": acct_valid}
    # accounts whose data lives in this schema (distinct account_rid across key tables)
    s_tables = {r[0] for r in _fetch(pool, "orgdb",
        "SELECT table_name FROM information_schema.tables WHERE table_schema=%s", [S])}
    A = set()
    for tbl in ("project", "account_fiscal", "project_fiscal"):
        if tbl not in s_tables:
            continue
        A |= {r[0] for r in _fetch(pool, "orgdb", S_.SQL(
            "SELECT DISTINCT account_rid FROM {s}.{t} WHERE account_rid IS NOT NULL"
        ).format(s=S_.Identifier(S), t=S_.Identifier(tbl))) if r[0]}
    log(f"  (main: {len(A)} account(s) own data in {S}; "
        f"org sets — project={len(org_sets['project_rid'])}, fiscal={len(org_sets['project_fiscal_rid'])}, case={len(org_sets['case_rid'])})")
    if not A:
        log("  (main: could not determine this schema's accounts — skipping main side)")
        return []

    # main tables + their org-entity columns
    rows = _fetch(pool, "maindb",
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND column_name = ANY(%s) ORDER BY table_name", [main_schema, ORG_ENTITY_COLS])
    tcols = defaultdict(set)
    for t, c in rows:
        tcols[t].add(c)

    results = []
    for t in sorted(tcols):
        if BACKUP_TABLE_RE.search(t) or t.endswith("_bk"):
            continue
        cols = tcols[t]
        if "account_rid" not in cols:
            results.append({"side": "MAIN", "table": t, "column": ", ".join(sorted(cols)),
                            "entity": "-", "orphans": "SKIP (no account_rid to scope to schema)", "samples": ""})
            continue
        # fetch this schema's rows once (account in A), with all org-entity cols present
        sel_cols = [c for c in ORG_ENTITY_COLS if c in cols]
        q = S_.SQL("SELECT {cols} FROM {ms}.{t} WHERE account_rid = ANY(%s)").format(
            cols=S_.SQL(", ").join(S_.Identifier(c) for c in sel_cols),
            ms=S_.Identifier(main_schema), t=S_.Identifier(t))
        data = _fetch(pool, "maindb", q, [list(A)])
        if not data:
            continue
        idx = {c: i for i, c in enumerate(sel_cols)}
        for col in sel_cols:
            valid = org_sets[col]
            orphan_vals = [row[idx[col]] for row in data
                           if row[idx[col]] is not None and row[idx[col]] not in valid]
            if orphan_vals:
                ent = {"project_rid": "project", "project_fiscal_rid": "project_fiscal",
                       "case_rid": "case", "account_rid": "account"}[col]
                results.append({"side": "MAIN", "table": t, "column": col, "entity": ent,
                                "orphans": len(orphan_vals),
                                "samples": "; ".join(str(x) for x in orphan_vals[:sample])})
    return results


def main():
    ap = argparse.ArgumentParser(description="Detailed orphan analysis for one schema across main + org.")
    ap.add_argument("--config", type=Path, default=HERE / "config" / "db_config.json")
    ap.add_argument("--schema", default="trd365_00416")
    ap.add_argument("--main-schema", default="trd365")
    ap.add_argument("--sample", type=int, default=3)
    ap.add_argument("--out-dir", type=Path, default=HERE / "reports")
    args = ap.parse_args()

    pool = db.ConnectionPool(db.load_config(args.config))
    S = args.schema
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log = print
    try:
        log("=" * 92)
        log(f"DETAILED ORPHAN ANALYSIS — schema {S}  (ORG + MAIN)")
        log("=" * 92)
        acct_valid = {r[0] for r in _fetch(pool, "maindb", S_.SQL("SELECT rid FROM {}.{}").format(
            S_.Identifier(args.main_schema), S_.Identifier("account")))}
        log(f"valid accounts in main.{args.main_schema}.account: {len(acct_valid)}\n")

        log("── ORG side ──────────────────────────────────────────────────────")
        org = org_side(pool, S, args.main_schema, acct_valid, args.sample, log)
        log("\n── MAIN side ─────────────────────────────────────────────────────")
        mn = main_side(pool, S, args.main_schema, acct_valid, args.sample, log)

        allr = org + mn
        args.out_dir.mkdir(parents=True, exist_ok=True)
        outp = args.out_dir / f"schema_orphans_{S}_{stamp}.csv"
        with open(outp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["side", "table", "column", "entity", "orphans", "samples"])
            w.writeheader(); w.writerows(allr)

        def tot(side):
            return sum(r["orphans"] for r in allr if r["side"] == side and isinstance(r["orphans"], int))
        log("\n" + "=" * 92)
        log(f"{'side':<6}{'table':<40}{'column':<26}{'orphans':>9}")
        log("-" * 92)
        for r in sorted(allr, key=lambda x: (x["side"], -(x["orphans"] if isinstance(x["orphans"], int) else 0))):
            log(f"{r['side']:<6}{r['table']:<40}{r['column']:<26}{str(r['orphans']):>9}   -> {r['entity']}")
        log("-" * 92)
        log(f"ORG orphan rows : {tot('ORG')}   |   MAIN orphan rows : {tot('MAIN')}")
        log(f"report: {outp}")
        log("=" * 92)
    finally:
        pool.close_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
