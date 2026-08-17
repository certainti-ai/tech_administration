#!/usr/bin/env python3
"""
Cross-tenant SharePoint site migration (document libraries + files + folders).

Copies one SharePoint site's document-library contents from a SOURCE tenant to a
DEST tenant (different domain) via Microsoft Graph, using two app-only tokens (one
per tenant — the tenants don't trust each other's app registration).

What it migrates:
  * every document library (or a chosen subset) → same-named library on the dest
    site (created if missing),
  * the full folder tree, and
  * every file (chunked upload session for large files), preserving
    created/modified timestamps.

What it does NOT migrate (by design — call these out to stakeholders):
  * permissions / sharing (identities differ across tenants — no 1:1 mapping),
  * version history (only current versions are copied),
  * SharePoint Lists (non-library), site pages, web parts, workflows,
  * metadata columns beyond name/timestamps.
These can be added later; the file/library core is the safe, high-value part.

Usage:
    python migrate.py --config config.json --dry-run     # enumerate, no writes
    python migrate.py --config config.json               # run (resumable)
    python migrate.py --config config.json --libraries "Documents,Policies"

Resumable: a manifest in state/ records every copied file; a re-run skips them.
Idempotent for folders (ensure/replace); files skipped unless --overwrite.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine.auth import TenantAuth          # noqa: E402
from engine.client import GraphClient, GraphError  # noqa: E402
from engine import resolve as R             # noqa: E402

STATE_DIR = HERE / "state"
LOG_DIR = HERE / "logs"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))[:80]


class Migrator:
    def __init__(self, cfg, dry_run=False, overwrite=None, log=print):
        self.cfg = cfg
        self.opt = cfg.get("options", {})
        self.dry_run = dry_run
        self.overwrite = self.opt.get("overwrite_existing", False) if overwrite is None else overwrite
        self.log = log
        self.threshold = int(self.opt.get("large_file_threshold_mb", 4)) * 1024 * 1024
        self.chunk = int(self.opt.get("chunk_size_mb", 10)) * 1024 * 1024
        self.preserve = self.opt.get("preserve_timestamps", True)
        self.src = GraphClient(TenantAuth.from_config("source", cfg["source"]))
        self.dst = GraphClient(TenantAuth.from_config("dest", cfg["dest"]))
        self.stats = {"libraries": 0, "folders": 0, "files": 0, "bytes": 0,
                      "skipped": 0, "errors": 0}
        self.manifest = {}
        self._mpath = None

    # ── manifest (resume) ────────────────────────────────────────────────────
    def _load_manifest(self, key):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._mpath = STATE_DIR / f"manifest_{key}.json"
        if self._mpath.exists():
            self.manifest = json.load(open(self._mpath))
        else:
            self.manifest = {"done": {}, "started_at": _now()}

    def _save_manifest(self):
        if self.dry_run or not self._mpath:
            return
        tmp = str(self._mpath) + ".tmp"
        json.dump(self.manifest, open(tmp, "w"), indent=2)
        os.replace(tmp, self._mpath)

    # ── run ──────────────────────────────────────────────────────────────────
    def run(self):
        src_site = R.get_site(self.src, self.cfg["source"]["site_url"])
        dst_site = R.get_site(self.dst, self.cfg["dest"]["site_url"])
        self.log(f"SOURCE site: {src_site.get('displayName')}  ({src_site['id'].split(',')[0]})")
        self.log(f"DEST   site: {dst_site.get('displayName')}  ({dst_site['id'].split(',')[0]})")
        self._load_manifest(_safe(src_site["id"]) + "__" + _safe(dst_site["id"]))

        want = self.opt.get("libraries")
        if isinstance(want, str):
            want = [x.strip() for x in want.split(",") if x.strip()]
        src_drives = R.list_drives(self.src, src_site["id"])
        dst_cache = {d.get("name"): d for d in R.list_drives(self.dst, dst_site["id"])}

        for sd in src_drives:
            name = sd.get("name")
            if want and name not in want:
                continue
            if sd.get("driveType") not in (None, "documentLibrary"):
                continue
            self.log(f"\n=== Library: {name} ===")
            dd, dst_cache = R.get_or_create_library_drive(
                self.dst, dst_site["id"], name,
                create=self.opt.get("create_missing_libraries", True), cache=dst_cache)
            if not dd:
                self.log(f"  ! dest library '{name}' missing and not created — skipping")
                continue
            self.stats["libraries"] += 1
            src_root = self.src.get(f"/drives/{sd['id']}/root")["id"]
            dst_root = self.dst.get(f"/drives/{dd['id']}/root")["id"] if not self.dry_run else None
            self._walk(sd["id"], src_root, dd["id"], dst_root, name)
            self._save_manifest()

        self._summary()
        return self.stats

    def run_since(self, since_iso):
        """Delta catch-up: copy ONLY source files modified/created after `since_iso`
        (created-after = new, modified-after = refreshed). Uses the Graph delta API
        to find them fast (no full re-walk), creates each file's dest folder path as
        needed, and overwrites. Ideal for reconciling changes made during a long run."""
        from datetime import datetime
        since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        self.overwrite = True  # changed files must replace stale dest copies
        src_site = R.get_site(self.src, self.cfg["source"]["site_url"])
        dst_site = R.get_site(self.dst, self.cfg["dest"]["site_url"])
        self.log(f"SOURCE: {src_site.get('displayName')}   DEST: {dst_site.get('displayName')}")
        self.log(f"delta catch-up: files changed since {since.isoformat()}")
        self._load_manifest(_safe(src_site["id"]) + "__" + _safe(dst_site["id"]))
        want = self.opt.get("libraries")
        if isinstance(want, str):
            want = [x.strip() for x in want.split(",") if x.strip()]
        dst_cache = {d.get("name"): d for d in R.list_drives(self.dst, dst_site["id"])}
        for sd in R.list_drives(self.src, src_site["id"]):
            name = sd.get("name")
            if want and name not in want:
                continue
            dd, dst_cache = R.get_or_create_library_drive(
                self.dst, dst_site["id"], name,
                create=self.opt.get("create_missing_libraries", True), cache=dst_cache)
            if not dd:
                continue
            dd_root = self.dst.get(f"/drives/{dd['id']}/root")["id"]
            pcache = {}
            self.log(f"\n=== Library: {name} — scanning for changes ===")
            url = (f"/drives/{sd['id']}/root/delta?$select=id,name,size,file,folder,"
                   f"lastModifiedDateTime,parentReference&$top=500")
            while url:
                data = self.src._req("GET", url, absolute=url.startswith("http")).json()
                for it in data.get("value", []):
                    if "file" not in it:
                        continue
                    lm = datetime.fromisoformat(it["lastModifiedDateTime"].replace("Z", "+00:00"))
                    if lm <= since:
                        continue
                    pref = (it.get("parentReference") or {}).get("path", "")
                    rel = pref.split("root:", 1)[-1].lstrip("/") if "root:" in pref else ""
                    cpath = f"{name}/{rel}/{it['name']}" if rel else f"{name}/{it['name']}"
                    try:
                        dst_parent = R.ensure_path(self.dst, dd["id"], dd_root, rel, pcache)
                    except Exception as exc:
                        self.log(f"  ! ERROR path {rel}: {str(exc)[:120]}")
                        self.stats["errors"] += 1
                        continue
                    self._copy_file(sd["id"], it, dd["id"], dst_parent, cpath)
                url = data.get("@odata.nextLink")
            self._save_manifest()
        self._summary()
        return self.stats

    def _walk(self, src_drive, src_folder, dst_drive, dst_folder, path):
        for child in R.iter_children(self.src, src_drive, src_folder):
            name = child["name"]
            cpath = f"{path}/{name}"
            if "folder" in child:
                self.log(f"  [dir]  {cpath}")
                self.stats["folders"] += 1
                if self.dry_run:
                    self._walk(src_drive, child["id"], dst_drive, None, cpath)
                else:
                    df = R.ensure_folder(self.dst, dst_drive, dst_folder, name)
                    self._walk(src_drive, child["id"], dst_drive, df["id"], cpath)
            elif "file" in child:
                self._copy_file(src_drive, child, dst_drive, dst_folder, cpath)

    def _copy_file(self, src_drive, item, dst_drive, dst_folder, cpath):
        key = f"{src_drive}/{item['id']}"
        size = int(item.get("size", 0))
        if not self.overwrite and key in self.manifest["done"]:
            self.stats["skipped"] += 1
            return
        if self.dry_run:
            self.log(f"  [file] {cpath}  ({_h(size)})  -> would copy")
            self.stats["files"] += 1
            self.stats["bytes"] += size
            return
        conflict = "replace" if self.overwrite else "fail"
        fsi = item.get("fileSystemInfo") if self.preserve else None
        try:
            # download with truncation guard. We only retry SHORT reads (got < size),
            # which signal a mid-stream network blip. An OVER-read (got > size) is NOT
            # corruption: Graph's driveItem `size` is metadata that legitimately differs
            # from the /content byte stream for Office files (.docx/.xlsx/.pptx get
            # repackaged on download). The downloaded bytes ARE the file, so we accept
            # them and upload using the ACTUAL on-disk size (`got`) — never the stale
            # metadata `size`, which would otherwise corrupt the upload Content-Range.
            tmp_path = None
            got = 0
            for dl_attempt in range(1, 4):
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp_path = tmp.name
                    self.src.download_to(src_drive, item["id"], tmp)
                got = os.path.getsize(tmp_path)
                if size == 0 or got >= size:
                    break
                os.unlink(tmp_path)  # short read — likely truncated, retry the download
                if dl_attempt == 3:
                    raise GraphError("download-size", item["id"],
                                     type("R", (), {"status_code": 0,
                                                    "text": f"short download: {got} of {size} bytes after 3 tries"})())
                time.sleep(2 * dl_attempt)
            upload_size = got  # authoritative: what we actually hold on disk
            try:
                if upload_size > self.threshold:
                    new = self.dst.upload_large(dst_drive, dst_folder, item["name"], tmp_path,
                                                upload_size, self.chunk, file_system_info=fsi, conflict=conflict)
                else:
                    with open(tmp_path, "rb") as fh:
                        new = self.dst.upload_small(dst_drive, dst_folder, item["name"], fh, conflict=conflict)
                    if fsi and new.get("id"):
                        try:
                            self.dst.patch(f"/drives/{dst_drive}/items/{new['id']}", json={"fileSystemInfo": fsi})
                        except GraphError:
                            pass
            finally:
                os.unlink(tmp_path)
            self.log(f"  [file] {cpath}  ({_h(upload_size)})  -> copied")
            self.stats["files"] += 1
            self.stats["bytes"] += upload_size
            self.manifest["done"][key] = {"name": item["name"], "size": upload_size,
                                          "dest_id": new.get("id"), "at": _now()}
            if self.stats["files"] % 25 == 0:
                self._save_manifest()
        except GraphError as e:
            if e.status == 409 and not self.overwrite:
                self.log(f"  [file] {cpath}  -> exists, skipped")
                self.stats["skipped"] += 1
            else:
                self.log(f"  ! ERROR {cpath}: {e}")
                self.stats["errors"] += 1

    def _summary(self):
        s = self.stats
        self.log("\n" + "=" * 70)
        self.log(f"{'DRY-RUN' if self.dry_run else 'MIGRATION'} SUMMARY")
        self.log(f"  libraries : {s['libraries']}")
        self.log(f"  folders   : {s['folders']}")
        self.log(f"  files     : {s['files']}  ({_h(s['bytes'])})")
        self.log(f"  skipped   : {s['skipped']}   errors: {s['errors']}")
        self.log("=" * 70)


def _h(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


def main():
    ap = argparse.ArgumentParser(description="Cross-tenant SharePoint site migration (Graph).")
    ap.add_argument("--config", type=Path, default=HERE / "config.json")
    ap.add_argument("--dry-run", action="store_true", help="Enumerate + report, no writes.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing dest files.")
    ap.add_argument("--libraries", help="Comma-separated library names to include (overrides config).")
    ap.add_argument("--since", help="Delta catch-up: copy only files modified/created after this "
                    "ISO timestamp (e.g. 2026-08-06T12:37:52Z). Overwrites; no full re-walk.")
    args = ap.parse_args()
    if not args.config.exists():
        sys.exit(f"Config not found: {args.config}  (copy config.example.json -> config.json)")
    cfg = json.load(open(args.config))
    if args.libraries:
        cfg.setdefault("options", {})["libraries"] = args.libraries

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(LOG_DIR / f"migrate_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log", "w")
    def log(m):
        print(m); logf.write(str(m) + "\n"); logf.flush()

    print("=" * 70)
    print(f"Cross-tenant SharePoint migration ({'DRY-RUN' if args.dry_run else 'LIVE'})")
    print("=" * 70)
    m = Migrator(cfg, dry_run=args.dry_run, overwrite=args.overwrite or None, log=log)
    try:
        if args.since:
            m.run_since(args.since)
        else:
            m.run()
    finally:
        m._save_manifest()
        logf.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Manifest saved — re-run to resume.")
        sys.exit(130)
