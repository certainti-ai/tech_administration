#!/usr/bin/env python3
"""
Turn a raw Jira search response for project HDM into the migration dashboard.

Why this exists
---------------
The dashboard is republished twice a day (09:00 and 18:00 IST) to a fixed
Artifact link. A scheduled Claude session cannot carry the page's markup or the
field mapping in its head, so both live here: the session's only job is to fetch
the JQL result and hand the JSON to this script.

Fetching is deliberately NOT this script's job. There is no Jira API token on
the maintenance hosts; the only credentialled path is the Atlassian MCP
connector, which is driven from a Claude session. So the session fetches, this
script transforms. See REFRESH.md for the runbook.

The custom fields below are Jira field IDs, which are per-site and not stable
across projects. They were read off HDM-1 with ``expand=names``; if a field is
renamed in Jira the ID keeps working, but if the project is rebuilt they must be
re-read.

Usage
-----
    # One or more raw search responses (paginated reads produce several).
    python tools/hdm_report/build_report.py \\
        --raw page1.json [page2.json ...] \\
        --template tools/hdm_report/template.html \\
        --out hdm-dashboard.html

    # Emit just the normalised rows, e.g. to diff two reads.
    python tools/hdm_report/build_report.py --raw page1.json --json-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import zoneinfo
from pathlib import Path

# Jira custom field IDs on certainti.atlassian.net, project HDM.
FIELDS = {
    "migStatus": "customfield_10461",
    "planned": "customfield_10462",
    "fiscal": "customfield_10463",
    "jurisdiction": "customfield_10464",
    "customer": "customfield_10465",
    "bizBlock": "customfield_10458",
}

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Zero-width and bidi controls that Jira comments pick up from pasted content.
ZERO_WIDTH = re.compile("[​-‏‪-‮⁠﻿­͏]")


def opt(fields: dict, key: str):
    """Read a Jira field that may be a scalar, a single option, or a list of them."""
    v = fields.get(key)
    if isinstance(v, dict):
        return v.get("value")
    if isinstance(v, list) and v:
        first = v[0]
        return first.get("value") if isinstance(first, dict) else first
    return v


def adf_text(node) -> str:
    """Flatten an ADF comment body to plain text.

    Comment bodies come back either as ADF documents or as markdown-ish strings
    with ``<custom>`` wrappers around mentions, depending on the response format
    the connector chose. Handle both.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "mention":
        return node.get("attrs", {}).get("text", "")
    if t == "emoji":
        return node.get("attrs", {}).get("shortName", "")
    if t == "media":
        return "[%s]" % (node.get("attrs", {}).get("alt") or "attachment")
    if t == "hardBreak":
        return " "
    return "".join(adf_text(c) for c in (node.get("content") or []))


def clean(text: str) -> str:
    """Strip comment markup down to readable prose."""
    if not text:
        return ""
    text = re.sub(r"<custom[^>]*>(.*?)</custom>", r"\1", text, flags=re.S)  # mentions
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # inline images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> label
    text = text.replace("|", "/")
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", ZERO_WIDTH.sub("", text)).strip()


def load_nodes(paths: list[Path]) -> list[dict]:
    """Collect issue nodes from one or more raw search responses, de-duplicated."""
    seen, nodes = set(), []
    for path in paths:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            sys.exit(f"{path}: not a readable Jira search response ({exc})")
        if not isinstance(payload, dict):
            sys.exit(f"{path}: expected a JSON object, got {type(payload).__name__}")
        page = payload.get("issues", payload)
        for node in page.get("nodes", page.get("issues", [])):
            if node["key"] not in seen:
                seen.add(node["key"])
                nodes.append(node)
    return nodes


def normalise(nodes: list[dict], today: dt.date) -> list[dict]:
    rows = []
    for node in nodes:
        f = node["fields"]

        comments = sorted(
            (f.get("comment") or {}).get("comments", []) or [],
            key=lambda c: c["created"],
        )
        history = [
            {"a": c["author"]["displayName"], "d": c["created"][:10], "t": clean(adf_text(c["body"]))}
            for c in comments[-4:]
        ]

        # Newest comment that actually carries text; screenshot-only comments are
        # common here and would otherwise render as an empty cell.
        with_text = [c for c in reversed(history) if c["t"]]
        if with_text:
            pick = with_text[0]
            last = {
                "author": pick["a"],
                "date": pick["d"],
                "text": pick["t"],
                "attachOnly": pick is not history[-1],
            }
        elif history:
            last = {
                "author": history[-1]["a"],
                "date": history[-1]["d"],
                "text": "(attachment only — no text)",
                "attachOnly": True,
            }
        else:
            last = None

        planned = f.get(FIELDS["planned"])
        row = {
            "key": node["key"],
            "summary": f["summary"].strip(),
            "customer": opt(f, FIELDS["customer"]),
            "jurisdiction": opt(f, FIELDS["jurisdiction"]),
            "fiscal": opt(f, FIELDS["fiscal"]),
            "status": f["status"]["name"],
            "statusCat": f["status"]["statusCategory"]["name"],
            "migStatus": opt(f, FIELDS["migStatus"]),
            "planned": planned,
            "assignee": (f.get("assignee") or {}).get("displayName"),
            "updated": f["updated"][:10],
            "bizBlock": opt(f, FIELDS["bizBlock"]),
            "nComments": len(comments),
            "lastComment": last,
            "lastTouch": last["date"] if last else None,
        }
        row["daysSinceComment"] = (
            (today - dt.date.fromisoformat(last["date"])).days if last else None
        )
        row["daysToPlanned"] = (
            (dt.date.fromisoformat(planned) - today).days if planned else None
        )
        rows.append(row)

    rows.sort(key=lambda r: int(r["key"].split("-")[1]))
    return rows


def build(rows: list[dict], template: Path, read_at: dt.datetime) -> str:
    keep = (
        "key customer jurisdiction fiscal status statusCat migStatus planned assignee "
        "summary lastComment lastTouch daysSinceComment daysToPlanned bizBlock nComments"
    ).split()
    slim = [{k: r.get(k) for k in keep} for r in rows]

    # Fixed, count-independent hue assignment: a status keeps its colour when
    # another status is filtered away.
    status_order = sorted({r["status"] for r in rows})

    meta = {
        "today": read_at.date().isoformat(),
        "readAt": read_at.isoformat(),
        "readAtLabel": read_at.strftime("%d %B %Y, %H:%M IST"),
        "taskCount": len(rows),
    }

    html = template.read_text()
    for token, value in (
        ("__DATA__", json.dumps(slim, separators=(",", ":"), ensure_ascii=False)),
        ("__META__", json.dumps(meta, separators=(",", ":"))),
        ("__STATUS_ORDER__", json.dumps(status_order, separators=(",", ":"))),
    ):
        if token not in html:
            sys.exit(f"template is missing the {token} placeholder")
        if "</script" in value.lower():
            sys.exit(f"refusing to inline {token}: it would close the script block")
        html = html.replace(token, value)
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", nargs="+", required=True, type=Path,
                    help="raw Jira search response(s) — one file per page")
    ap.add_argument("--template", type=Path,
                    default=Path(__file__).with_name("template.html"))
    ap.add_argument("--out", type=Path, default=Path("hdm-dashboard.html"))
    ap.add_argument("--json-only", action="store_true",
                    help="print the normalised rows and exit")
    args = ap.parse_args()

    read_at = dt.datetime.now(IST)
    nodes = load_nodes(args.raw)
    if not nodes:
        sys.exit("no issues found in the raw response — check the JQL and the field list")
    rows = normalise(nodes, read_at.date())

    if args.json_only:
        json.dump(rows, sys.stdout, indent=1)
        return

    args.out.write_text(build(rows, args.template, read_at))

    missing = [r["key"] for r in rows if not r["migStatus"]]
    print(f"{len(rows)} tasks → {args.out} (read {read_at:%Y-%m-%d %H:%M} IST)")
    print("  migration status: " + ", ".join(
        f"{v} {k}" for k, v in sorted(
            ((k, sum(1 for r in rows if r["migStatus"] == k))
             for k in {r["migStatus"] for r in rows} if k),
            key=lambda kv: -kv[1])))
    if missing:
        print(f"  WARNING: no Migration Status on {len(missing)}: {', '.join(missing)}")


if __name__ == "__main__":
    main()
