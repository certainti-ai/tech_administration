#!/usr/bin/env python3
"""Re-classify naming deviations using GLOBAL (cross-schema) frequency.

The per-schema classifier in model_analysis.py can mislabel a global-lookup
reference as a typo when that reference happens to appear in only 1-2 tables in a
single schema. This post-processor pools deviations across all schemas and uses
each `{prefix}_rid`'s global footprint to decide:

  * polymorphic   — entity_rid / attach_to / … (reference type varies by a
                    companion column; not resolvable to one parent)
  * global-lookup — prefix seen in >= GLOBAL_MIN distinct (schema,table) pairs:
                    a shared entity whose parent table lives in another schema
  * LIKELY-TYPO   — rare prefix that closely matches an established reference
                    name but isn't equal (genuine human error)
  * unresolved    — rare, no close match (review)

Reads one or more deviations_*.csv, writes deviations_reclassified_<ts>.csv and
prints the confirmed likely-typos.

Usage:
    python reclassify_deviations.py reports/deviations_A.csv reports/deviations_B.csv
"""
import csv
import difflib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

POLYMORPHIC = {"entity_rid", "attach_to", "related_to_rid", "reference_rid",
               "parent_rid", "source_rid", "target_rid", "attached_to_rid"}
POLY_PREFIX = {"entity", "related_to", "reference", "parent", "source", "target"}
GLOBAL_MIN = 3       # prefix in >= N distinct (schema,table) pairs => global entity
KNOWN_MIN = 8        # prefix this frequent => part of the reference "vocabulary"
TYPO_CUTOFF = 0.86


def main():
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit("usage: python reclassify_deviations.py <deviations_csv> [more...]")
    rows = []
    for p in paths:
        rows.extend(csv.DictReader(open(p)))

    # global footprint of each _rid prefix
    footprint = defaultdict(set)      # prefix -> {(schema, table)}
    for r in rows:
        col = r["column"]
        if col.endswith("_rid"):
            footprint[col[:-4]].add((r["schema"], r["child_table"]))
    freq = {p: len(s) for p, s in footprint.items()}
    vocabulary = {p for p, n in freq.items() if n >= KNOWN_MIN}  # established names

    out, typos = [], []
    for r in rows:
        col = r["column"]; prefix = col[:-4] if col.endswith("_rid") else col
        if col in POLYMORPHIC or prefix in POLY_PREFIX:
            cl, note = "polymorphic", ""
        elif freq.get(prefix, 0) >= GLOBAL_MIN:
            cl, note = "global-lookup", f"(global footprint: {freq[prefix]} tables)"
        else:
            m = difflib.get_close_matches(prefix, list(vocabulary - {prefix}), n=1, cutoff=TYPO_CUTOFF)
            if m:
                cl, note = "LIKELY-TYPO", f"-> did you mean '{m[0]}_rid'? ({prefix} only in {freq.get(prefix,0)} table(s))"
                typos.append({**r, "classification": cl, "note": note})
            else:
                cl, note = "unresolved", f"(rare: {freq.get(prefix,0)} table(s))"
        out.append({"schema": r["schema"], "child_table": r["child_table"], "column": col,
                    "classification": cl, "note": note})

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outp = paths[0].parent / f"deviations_reclassified_{stamp}.csv"
    with open(outp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["schema", "child_table", "column", "classification", "note"])
        w.writeheader(); w.writerows(out)

    cnt = Counter(o["classification"] for o in out)
    print(f"reclassified {len(out)} deviation rows from {len(paths)} file(s)")
    print(f"  polymorphic={cnt.get('polymorphic',0)}  global-lookup={cnt.get('global-lookup',0)}  "
          f"unresolved={cnt.get('unresolved',0)}  LIKELY-TYPO={cnt.get('LIKELY-TYPO',0)}")
    print(f"  written: {outp}\n")
    if typos:
        print("CONFIRMED LIKELY HUMAN-ERROR TYPOS (global-frequency filtered):")
        seen = set()
        for t in sorted(typos, key=lambda x: (x["column"], x["schema"])):
            key = (t["schema"], t["child_table"], t["column"])
            if key in seen:
                continue
            seen.add(key)
            print(f"  {t['schema']}.{t['child_table']}.{t['column']}   {t['note']}")
    else:
        print("No likely-typos survive global-frequency filtering — naming is consistent.")


if __name__ == "__main__":
    main()
