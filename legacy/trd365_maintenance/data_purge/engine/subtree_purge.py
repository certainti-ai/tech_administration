"""
Generic subtree purge — for sub-entities whose deletion is a pure subtree removal
with NO surviving-parent recompute (case, interaction, …).

Wraps engine/core.py: resolve → backup+delete (children-first, multi-pass FK) →
audit → build a run dict for engine/report.py. The caller supplies the manifest
STEPS and an entity Scoper (.predicate / optional .discover), exactly like the
account sub-module — this just removes the per-entity boilerplate.
"""

from datetime import datetime, timezone

from engine import core


def _now():
    return datetime.now(timezone.utc)


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))


def purge_entity(pool, entity, entity_rid, schema_for, steps, scoper,
                 chunk_size=1000, dry_run=True, log=print, context=None):
    """Run backup+delete+audit for one sub-entity. Returns (run_dict, ok)."""
    run_id = f"{entity}_{_safe(entity_rid)}_{_now().strftime('%Y%m%d_%H%M%S')}"
    run = {
        "entity": entity, "entity_rid": entity_rid, "run_id": run_id,
        "backup_schema": core.BACKUP_SCHEMA, "started_at": _now().isoformat(),
        "context": context or {}, "metrics": {}, "completed_tables": {},
        "status": "in_progress", "last_error": None,
        "steps_meta": [{"step": s, "db": d, "schema": schema_for[k]} for (s, d, k, _t) in steps],
    }
    tag = (run["started_at"], run_id, entity, entity_rid)

    log(f"  [1/5] ANALYSE + [2/5+3/5] {'(dry-run: counts only)' if dry_run else 'BACKUP + DELETE'} "
        f"(children-first)…")
    ok, err = core.run_steps(pool, steps, schema_for, scoper, tag, core.BACKUP_SCHEMA,
                             chunk_size, dry_run, log, run["metrics"], run["completed_tables"],
                             lambda: None)
    if not ok:
        run["status"] = "failed"; run["last_error"] = err

    findings, clean = ([], None)
    if ok:
        findings, clean = core.audit(pool, steps, schema_for, scoper, run["metrics"], dry_run, log)
    run["audit"] = {"findings": findings, "clean": clean}
    if ok:
        run["status"] = ("dry-run-complete" if dry_run
                         else ("completed" if clean else "completed-with-audit-warnings"))
    run["finished_at"] = _now().isoformat()
    return run, ok
