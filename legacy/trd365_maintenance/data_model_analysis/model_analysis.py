#!/usr/bin/env python3
"""Entity dependency + orphan analysis for the Main/Org data model.

Convention: most tables have a primary key column `rid`, referenced elsewhere as
`{entity}_rid` (project.rid -> project_rid). The four PRIMARY entities and their
parent tables (auto-discovered, with real naming deviations):

    account  -> main.trd365.account          (cross-DB: referenced from org)
    project  -> <org tenant schema>.project
    resource -> <org tenant schema>.resources   (plural)
    case     -> <org tenant schema>.cases       (plural; referenced as case_rid)

Per org tenant schema this tool:
  1. catalogs tables + `_rid` columns,
  2. resolves each `_rid` column to its parent (plural-aware; account cross-DB),
  3. builds the dependency structure,
  4. finds ORPHAN rows (non-null {entity}_rid absent from parent.rid),
  5. classifies naming DEVIATIONS into: likely human-error TYPOS, expected
     global-lookup refs (parent lives in a shared schema), and polymorphic refs.

Outputs a console summary and CSV files under --out-dir.

Usage:
    python model_analysis.py --org-schema trd365_00042
    python model_analysis.py --all-org-schemas               # sweep every tenant schema
    python model_analysis.py --org-schema trd365_00042 --all-entities --sample 3
    python model_analysis.py --all-org-schemas --no-orphans   # structure+deviations only (cheap)
"""

import argparse
import csv
import difflib
import re
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

QUERY_TIMEOUT = 90  # seconds; guards against tunnel-death hangs (dead socket, no read timeout)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db  # noqa: E402
try:
    from psycopg2 import sql as _sql
except ImportError:
    sys.exit("psycopg2 required. pip install -r requirements.txt")

PRIMARY = ["account", "resource", "project", "case"]
# Columns / prefixes that reference different entity types by a companion type
# column — cannot be resolved to a single parent table (by design, not an error).
POLYMORPHIC = {"entity_rid", "attach_to", "related_to_rid", "reference_rid",
               "parent_rid", "source_rid", "target_rid", "attached_to_rid"}
POLY_PREFIX = {"entity", "related_to", "reference", "parent", "source", "target"}
GLOBAL_LOOKUP_MIN_TABLES = 3   # an unresolved prefix seen in >= N tables = shared entity
TYPO_CUTOFF = 0.84             # fuzzy similarity to flag a likely human-error typo
BACKUP_TABLE_RE = re.compile(r"^(backup|bak)_|_backup_|_bak_|backup_[0-9]", re.I)


def _fetch(pool, dbk, query, params=None, timeout=QUERY_TIMEOUT):
    """Run a read query with a watchdog timeout. If a dropped tunnel leaves the
    socket dead (psycopg2 has no read timeout), we drop the connection to abort
    the hung read and raise, so the caller can skip/continue instead of hanging."""
    conn = pool.get(dbk)
    box = {}

    def work():
        try:
            cur = conn.cursor()
            cur.execute(query, params) if params is not None else cur.execute(query)
            box["rows"] = cur.fetchall()
            cur.close()
            conn.rollback()
        except BaseException as exc:  # noqa: BLE001 - reported to caller
            box["err"] = exc

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pool.drop(dbk)  # close the socket to unblock the hung query; next get() reconnects
        raise TimeoutError(f"query timed out after {timeout}s on {dbk} (tunnel likely dropped)")
    if "err" in box:
        raise box["err"]
    return box["rows"]


def catalog(pool, dbk, schema):
    rows = _fetch(pool, dbk,
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = %s ORDER BY table_name, ordinal_position", [schema])
    cat = {}
    for t, c in rows:
        d = cat.setdefault(t, {"has_rid": False, "rid_cols": []})
        if c == "rid":
            d["has_rid"] = True
        if c.endswith("_rid"):
            d["rid_cols"].append(c)
    return cat


def resolve_parent(col, tables_with_rid):
    """`{prefix}_rid` -> parent table name (plural-aware). Returns (table, note)|(None,None)."""
    prefix = col[:-4]
    cands = [prefix, prefix + "s", prefix + "es"]
    if prefix.endswith("y"):
        cands.append(prefix[:-1] + "ies")
    for c in cands:
        if c in tables_with_rid:
            return c, ("" if c == prefix else f"plural:{prefix}->{c}")
    return None, None


def analyze_schema(pool, S, main_schema, acct_parent, acct_valid,
                   do_orphans, all_entities, sample, log):
    """Analyze one org tenant schema. Returns dict(edges, orphans, deviations)."""
    org_cat = catalog(pool, "orgdb", S)
    rid_tables = {t for t, d in org_cat.items() if d["has_rid"]}

    edges, deviations, unresolved = [], [], []
    for t, d in sorted(org_cat.items()):
        if BACKUP_TABLE_RE.search(t):
            continue  # skip backup/staging-of-backup tables
        for col in d["rid_cols"]:
            prefix = col[:-4]
            if col == "account_rid":
                if acct_parent:
                    edges.append((t, col, "account", "maindb", main_schema, "account", "cross-DB"))
                continue
            ptbl, note = resolve_parent(col, rid_tables)
            if ptbl:
                ek = {"project": "project", "resources": "resource", "cases": "case"}.get(ptbl, ptbl)
                edges.append((t, col, ek, "orgdb", S, ptbl, note))
            else:
                unresolved.append((t, col, prefix))

    # ── classify deviations ───────────────────────────────────────────────────
    pref_freq = Counter(p for _, _, p in unresolved)
    for t, col, prefix in unresolved:
        if col in POLYMORPHIC or prefix in POLY_PREFIX:
            deviations.append((t, col, "polymorphic", ""))
        elif pref_freq[prefix] >= GLOBAL_LOOKUP_MIN_TABLES:
            deviations.append((t, col, "global-lookup", f"({prefix} referenced in {pref_freq[prefix]} tables)"))
        else:
            m = difflib.get_close_matches(prefix, list(rid_tables), n=1, cutoff=TYPO_CUTOFF)
            if m:
                deviations.append((t, col, "LIKELY-TYPO", f"-> did you mean '{m[0]}_rid'?"))
            else:
                deviations.append((t, col, "unresolved", ""))

    # ── orphan detection ──────────────────────────────────────────────────────
    orphans = []
    if do_orphans:
        check = edges if all_entities else [e for e in edges if e[2] in PRIMARY]
        for (t, col, ek, dk, ps, pt, note) in sorted(check):
            try:
                if ek == "account":
                    grp = _fetch(pool, "orgdb", _sql.SQL(
                        "SELECT {c}, count(*) FROM {s}.{t} WHERE {c} IS NOT NULL GROUP BY {c}"
                    ).format(c=_sql.Identifier(col), s=_sql.Identifier(S), t=_sql.Identifier(t)))
                    bad = [(rid, n) for rid, n in grp if rid not in acct_valid]
                    cnt = sum(n for _, n in bad)
                    samp = [rid for rid, _ in bad][:sample]
                else:
                    cnt = _fetch(pool, dk, _sql.SQL(
                        "SELECT count(*) FROM {ps}.{t} c WHERE c.{col} IS NOT NULL "
                        "AND NOT EXISTS (SELECT 1 FROM {ps}.{pt} p WHERE p.rid=c.{col})"
                    ).format(ps=_sql.Identifier(ps), t=_sql.Identifier(t),
                             col=_sql.Identifier(col), pt=_sql.Identifier(pt)))[0][0]
                    samp = []
                    if cnt and sample:
                        samp = [r[0] for r in _fetch(pool, dk, _sql.SQL(
                            "SELECT DISTINCT c.{col} FROM {ps}.{t} c WHERE c.{col} IS NOT NULL "
                            "AND NOT EXISTS (SELECT 1 FROM {ps}.{pt} p WHERE p.rid=c.{col}) LIMIT %s"
                        ).format(ps=_sql.Identifier(ps), t=_sql.Identifier(t),
                                 col=_sql.Identifier(col), pt=_sql.Identifier(pt)), [sample])]
                if cnt:
                    orphans.append({"schema": S, "child_table": t, "column": col, "entity": ek,
                                    "parent_table": pt, "orphan_rows": cnt,
                                    "sample_rids": "; ".join(str(x) for x in samp)})
            except Exception as exc:
                orphans.append({"schema": S, "child_table": t, "column": col, "entity": ek,
                                "parent_table": pt, "orphan_rows": "ERR",
                                "sample_rids": str(exc).strip()[:60]})
    return {"edges": edges, "orphans": orphans, "deviations": deviations,
            "n_tables": len(org_cat), "rid_tables": rid_tables}


def main():
    ap = argparse.ArgumentParser(description="Entity dependency + orphan analysis.")
    ap.add_argument("--config", type=Path, default=HERE / "config" / "db_config.json")
    ap.add_argument("--org-schema", help="Single org tenant schema, e.g. trd365_00042")
    ap.add_argument("--schemas", help="Comma-separated list of org tenant schemas to run.")
    ap.add_argument("--all-org-schemas", action="store_true",
                    help="Sweep every trd365_* tenant schema (excludes backups).")
    ap.add_argument("--main-schema", default="trd365")
    ap.add_argument("--all-entities", action="store_true",
                    help="Orphan-check every resolved reference, not just the 4 primary entities.")
    ap.add_argument("--no-orphans", action="store_true", help="Structure + deviations only.")
    ap.add_argument("--sample", type=int, default=3, help="Example orphan rids per edge.")
    ap.add_argument("--out-dir", type=Path, default=HERE / "reports")
    args = ap.parse_args()
    if not args.org_schema and not args.all_org_schemas and not args.schemas:
        ap.error("provide --org-schema <name>, --schemas a,b,c, or --all-org-schemas")

    pool = db.ConnectionPool(db.load_config(args.config))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    orphans_csv = args.out_dir / f"orphans_{stamp}.csv"
    devi_csv = args.out_dir / f"deviations_{stamp}.csv"
    log = print
    try:
        # resolve account parent + preload valid account rids once
        acct_parent = bool(_fetch(pool, "maindb",
            "SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND "
            "table_name='account' AND column_name='rid'", [args.main_schema]))
        acct_valid = set()
        if acct_parent and not args.no_orphans:
            acct_valid = {r[0] for r in _fetch(pool, "maindb", _sql.SQL(
                "SELECT rid FROM {}.{}").format(_sql.Identifier(args.main_schema),
                                                _sql.Identifier("account")))}

        # schema list
        if args.all_org_schemas:
            schemas = [r[0] for r in _fetch(pool, "orgdb",
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'trd365\\_%' ESCAPE '\\' "
                "AND nspname NOT LIKE '%backup%' ORDER BY 1")]
        elif args.schemas:
            schemas = [s.strip() for s in args.schemas.split(",") if s.strip()]
        else:
            schemas = [args.org_schema]

        log("=" * 92)
        log(f"ENTITY DEPENDENCY + ORPHAN ANALYSIS  |  {len(schemas)} schema(s)  |  "
            f"account via main.{args.main_schema} ({len(acct_valid)} valid rids)")
        log(f"orphan scan: {'OFF' if args.no_orphans else ('ALL entities' if args.all_entities else '4 primary entities')}")
        log("=" * 92)

        ofh = open(orphans_csv, "w", newline=""); ow = csv.DictWriter(
            ofh, fieldnames=["schema", "child_table", "column", "entity", "parent_table", "orphan_rows", "sample_rids"]); ow.writeheader()
        dfh = open(devi_csv, "w", newline=""); dw = csv.DictWriter(
            dfh, fieldnames=["schema", "child_table", "column", "classification", "note"]); dw.writeheader()

        grand = {"orphan_rows": 0, "typos": 0, "schemas_ok": 0, "schemas_err": 0}
        for i, S in enumerate(schemas, 1):
            try:
                res = analyze_schema(pool, S, args.main_schema, acct_parent, acct_valid,
                                     not args.no_orphans, args.all_entities, args.sample, log)
            except Exception as exc:
                grand["schemas_err"] += 1
                log(f"\n[{i}/{len(schemas)}] {S}: ERROR {type(exc).__name__}: {str(exc).strip()[:80]} — skipped")
                pool.drop_all()
                continue
            grand["schemas_ok"] += 1
            sch_orphans = sum(o["orphan_rows"] for o in res["orphans"] if isinstance(o["orphan_rows"], int))
            grand["orphan_rows"] += sch_orphans
            typos = [d for d in res["deviations"] if d[2] == "LIKELY-TYPO"]
            grand["typos"] += len(typos)
            # write CSVs
            for o in res["orphans"]:
                ow.writerow(o)
            for (t, c, cl, note) in res["deviations"]:
                dw.writerow({"schema": S, "child_table": t, "column": c, "classification": cl, "note": note})
            ofh.flush(); dfh.flush()

            # per-schema console summary
            dev_counts = Counter(d[2] for d in res["deviations"])
            log(f"\n[{i}/{len(schemas)}] {S}: {res['n_tables']} tables | "
                f"orphan_rows={sch_orphans} across {len([o for o in res['orphans'] if isinstance(o['orphan_rows'],int) and o['orphan_rows']])} edge(s) | "
                f"deviations: typo={dev_counts.get('LIKELY-TYPO',0)} global={dev_counts.get('global-lookup',0)} "
                f"poly={dev_counts.get('polymorphic',0)} unresolved={dev_counts.get('unresolved',0)}")
            if typos:
                log("     LIKELY HUMAN-ERROR TYPOS:")
                for t, c, cl, note in typos:
                    log(f"       {t}.{c}  {note}")
            if not args.all_org_schemas:  # single-schema: show top orphan edges
                top = sorted([o for o in res["orphans"] if isinstance(o["orphan_rows"], int)],
                             key=lambda o: o["orphan_rows"], reverse=True)[:12]
                if top:
                    log("     top orphan edges:")
                    for o in top:
                        log(f"       {o['child_table']}.{o['column']:<22} {o['orphan_rows']:>7}  -> {o['entity']}")
        ofh.close(); dfh.close()

        log("\n" + "=" * 92)
        log(f"DONE — schemas ok={grand['schemas_ok']} err={grand['schemas_err']} | "
            f"TOTAL orphan rows={grand['orphan_rows']} | likely-typo deviations={grand['typos']}")
        log(f"orphans CSV    : {orphans_csv}")
        log(f"deviations CSV : {devi_csv}")
        log("=" * 92)
    finally:
        pool.close_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
