import json, pathlib
from collections import Counter, defaultdict

data = json.loads(pathlib.Path("changes.json").read_text())
BASE, EXCLUDED = data["baseline"], data["excluded"]
PREFIX = "r082506_"
ROOT = pathlib.Path("/home/user/tech_administration/sql/r082506-align-tenant-schemas")

WIDENING = {("integer", "numeric"), ("integer", "bigint"), ("smallint", "integer"),
            ("date", "timestamp with time zone"), ("character varying", "text"),
            ("USER-DEFINED", "character varying"),
            ("timestamp without time zone", "timestamp with time zone")}

def render(c):
    t, udt, ln, p, s = c["type"], c["udt"], c["length"], c["precision"], c["scale"]
    if t == "USER-DEFINED": return udt
    if t == "character varying": return f"varchar({ln})" if ln else "varchar"
    if t == "numeric" and p: return f"numeric({p},{s or 0})"
    return t

import re as _re

def tenant_specific(default):
    """
    Whether a default encodes which tenant it belongs to.

    Three shapes do, and every one of them would be catastrophic to copy from
    one schema to another:

    * ``nextval('trd365_00440.foo_seq')`` — the sequence is named by schema, so
      aligning points this tenant's ids at another tenant's counter;
    * ``('P001-' || gen_random_uuid())`` — the literal prefix *is* the tenant code;
    * ``('${ENV_PREFIX}' || …)`` — an unsubstituted template, wrong everywhere,
      but not wrong in a way another schema's copy would fix.

    Anything matching is left exactly as it is.
    """
    if not default:
        return False
    text = str(default)
    return (
        "nextval" in text
        or "regclass" in text
        or "${" in text
        or bool(_re.search(r"'[A-Z]{1,4}\d{3}-'", text))
    )


def classify(ch):
    """Riskiest aspect of one column change, aligning current -> baseline."""
    if ch["op"] == "add":
        return "add"
    b, o = ch["base"], ch["current"]
    if b["type"] != o["type"]:
        if (o["type"], b["type"]) in WIDENING: return "widen"
        if (b["type"], o["type"]) in WIDENING: return "narrow"
        return "narrow"                      # unknown conversions are treated as unsafe
    if b["length"] != o["length"] and b["type"] == "character varying":
        if b["length"] is None: return "widen"
        if o["length"] is None or b["length"] < o["length"]: return "narrow"
        return "widen"
    if (b["precision"], b["scale"]) != (o["precision"], o["scale"]): return "narrow"
    if b["nullable"] != o["nullable"]:
        return "loosen" if b["nullable"] == "YES" else "tighten"
    if tenant_specific(b["default"]) or tenant_specific(o["default"]):
        return "identity"
    return "default"

def q(s): return f'"{s}"'

def statements(sch, tbl, ch):
    """(forward, undo) statement lists for one column change."""
    t, c = f"{q(sch)}.{q(tbl)}", q(ch["col"])
    fwd, undo = [], []
    if ch["op"] == "add":
        b = ch["base"]
        fwd.append(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} {render(b)};")
        if b["default"] and b["default"] != "__SEQ_EQUIV__":
            fwd.append(f"ALTER TABLE {t} ALTER COLUMN {c} SET DEFAULT {b['default']};")
        undo.append(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {c};")
        return fwd, undo

    b, o = ch["base"], ch["current"]
    if render(b) != render(o):
        using = f" USING {c}::{render(b)}"
        fwd.append(f"ALTER TABLE {t} ALTER COLUMN {c} TYPE {render(b)}{using};")
        undo.append(f"ALTER TABLE {t} ALTER COLUMN {c} TYPE {render(o)} USING {c}::{render(o)};")
    if b["nullable"] != o["nullable"]:
        fwd.append(f"ALTER TABLE {t} ALTER COLUMN {c} "
                   f"{'DROP' if b['nullable'] == 'YES' else 'SET'} NOT NULL;")
        undo.append(f"ALTER TABLE {t} ALTER COLUMN {c} "
                    f"{'DROP' if o['nullable'] == 'YES' else 'SET'} NOT NULL;")
    if (b["default"] != o["default"]
            and "__SEQ_EQUIV__" not in (b["default"], o["default"])
            and not tenant_specific(b["default"]) and not tenant_specific(o["default"])):
        fwd.append(f"ALTER TABLE {t} ALTER COLUMN {c} "
                   + (f"SET DEFAULT {b['default']};" if b["default"] else "DROP DEFAULT;"))
        undo.append(f"ALTER TABLE {t} ALTER COLUMN {c} "
                    + (f"SET DEFAULT {o['default']};" if o["default"] else "DROP DEFAULT;"))
    return fwd, undo

TIERS = ["add", "widen", "loosen", "default", "tighten", "narrow", "identity"]
AUTO = {"add", "widen", "loosen", "default", "tighten"}
SKIP = {"narrow", "identity"}

tally = Counter()
per_schema = {}
for sch, tables in sorted(data["changes"].items()):
    buckets = {t: [] for t in TIERS}
    for tbl in sorted(tables):
        for ch in tables[tbl]:
            tier = classify(ch)
            tally[tier] += 1
            buckets[tier].append((tbl, ch))
    per_schema[sch] = buckets

print("change set, by risk tier:")
for t in TIERS:
    print(f"  {tally[t]:>4}  {t}")
print(f"\n  {sum(tally.values())} total across {len(per_schema)} schemas")
pathlib.Path("tiers.json").write_text(json.dumps({t: tally[t] for t in TIERS}))

# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------
HEADER = """-- {title}
-- Generated {when} from the live definition of {schema_desc}.
-- Baseline: {base}.  {excluded} is deliberately excluded.
--
-- Run with psql.  ON_ERROR_STOP is on and every schema is one transaction:
-- a statement that fails rolls its whole schema back and stops the run.
\\set ON_ERROR_STOP on
"""

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

WHEN = "2026-08-25"
touched = defaultdict(set)     # schema -> tables needing a backup
for sch, buckets in per_schema.items():
    for tier in AUTO:
        for tbl, _ in buckets[tier]:
            touched[sch].add(tbl)

long_names = [(s, t) for s, ts in touched.items() for t in ts if len(PREFIX + t) > 63]

# ---- 01 backup
for sch in sorted(touched):
    lines = [HEADER.format(title=f"Backup — {sch}", when=WHEN, base=BASE,
                           excluded=EXCLUDED, schema_desc=sch), ""]
    lines.append("BEGIN;")
    lines.append(f"SET LOCAL search_path = {q(sch)};")
    lines.append("")
    for tbl in sorted(touched[sch]):
        b = PREFIX + tbl
        lines += [f"-- {tbl}",
                  f"CREATE TABLE {q(sch)}.{q(b)} AS SELECT * FROM {q(sch)}.{q(tbl)};",
                  f"COMMENT ON TABLE {q(sch)}.{q(b)} IS "
                  f"'r082506 pre-alignment copy of {tbl}, taken {WHEN}';", ""]
    lines.append("-- Row counts must match before anything is altered.")
    lines.append("DO $$")
    lines.append("DECLARE t text; a bigint; b bigint;")
    lines.append("BEGIN")
    lines.append(f"  FOREACH t IN ARRAY ARRAY[{', '.join(repr(x) for x in sorted(touched[sch]))}] LOOP")
    lines.append(f"    EXECUTE format('SELECT count(*) FROM %I.%I', '{sch}', t) INTO a;")
    lines.append(f"    EXECUTE format('SELECT count(*) FROM %I.%I', '{sch}', '{PREFIX}' || t) INTO b;")
    lines.append("    IF a IS DISTINCT FROM b THEN")
    lines.append("      RAISE EXCEPTION 'backup row count mismatch for %: % vs %', t, a, b;")
    lines.append("    END IF;")
    lines.append("  END LOOP;")
    lines.append("END $$;")
    lines += ["", "COMMIT;"]
    write(ROOT / "01_backup" / f"{sch}.sql", "\n".join(lines) + "\n")

# ---- 02 align, 03 undo
for sch, buckets in sorted(per_schema.items()):
    fwd_all, undo_all, held = [], [], []
    for tier in TIERS:
        entries = buckets[tier]
        if not entries:
            continue
        if tier == "identity":
            continue
        target = held if tier == "narrow" else fwd_all
        target.append(f"\n-- ---- {tier} ({len(entries)}) "
                      + "-" * max(0, 56 - len(tier) - len(str(len(entries)))))
        for tbl, ch in entries:
            f, u = statements(sch, tbl, ch)
            if tier == "tighten":
                col = q(ch["col"])
                target.append(
                    f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {q(sch)}.{q(tbl)} "
                    f"WHERE {col} IS NULL) THEN RAISE EXCEPTION "
                    f"'{tbl}.{ch['col']} still has NULLs — cannot set NOT NULL'; END IF; END $$;")
            target += ([f"-- {tbl}.{ch['col']}: {render(ch['current'])} -> {render(ch['base'])}"]
                       if tier == "narrow" else [])
            target += f
            if tier != "narrow":
                undo_all = u + undo_all          # undo runs in reverse order
    lines = [HEADER.format(title=f"Align to baseline — {sch}", when=WHEN, base=BASE,
                           excluded=EXCLUDED, schema_desc=sch), "",
             f"-- Run 01_backup/{sch}.sql first.", "",
             "BEGIN;", f"SET LOCAL search_path = {q(sch)};", ""]
    lines += fwd_all if fwd_all else ["-- nothing in the automatic tiers for this schema"]
    lines += ["", "COMMIT;"]
    if held:
        lines += ["", "-- " + "=" * 68,
                  "-- HELD BACK — these NARROW the column and can lose data.",
                  "-- Measure first, decide, then run by hand.  See held_back.sql.",
                  "-- " + "=" * 68]
        lines += ["-- " + l if l.strip() else l for l in held]
    write(ROOT / "02_align" / f"{sch}.sql", "\n".join(lines) + "\n")

    ulines = [HEADER.format(title=f"Undo — {sch}", when=WHEN, base=BASE,
                            excluded=EXCLUDED, schema_desc=sch), "",
              "-- Restores the column definitions recorded before alignment.",
              "-- Data is not restored: see the note at the foot of this file.", "",
              "BEGIN;", f"SET LOCAL search_path = {q(sch)};", ""]
    ulines += undo_all if undo_all else ["-- nothing was altered in this schema"]
    ulines += ["", "COMMIT;", "",
               "-- If a type conversion mangled values, the pre-change data is in",
               f"-- {sch}.{PREFIX}<table>.  Restoring it is a deliberate act:",
               "--   BEGIN;",
               f"--   DELETE FROM {q(sch)}.\"<table>\";",
               f"--   INSERT INTO {q(sch)}.\"<table>\" SELECT * FROM {q(sch)}.\"{PREFIX}<table>\";",
               "--   COMMIT;"]
    write(ROOT / "03_undo" / f"{sch}.sql", "\n".join(ulines) + "\n")

# ---- all-schema drivers
for stage, folder in (("backup", "01_backup"), ("align", "02_align"), ("undo", "03_undo")):
    names = sorted(p.stem for p in (ROOT / folder).glob("*.sql"))
    body = [HEADER.format(title=f"Every schema — {stage}", when=WHEN, base=BASE,
                          excluded=EXCLUDED, schema_desc=f"{len(names)} tenant schemas"), ""]
    body += [f"\\echo '== {stage}: {n}'\n\\i {folder}/{n}.sql" for n in names]
    write(ROOT / f"{folder}_all.sql", "\n".join(body) + "\n")

print("wrote", sum(1 for _ in ROOT.rglob("*.sql")), "files under", ROOT)
print("backup name too long for:", long_names or "none")
