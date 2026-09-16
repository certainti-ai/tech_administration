#!/usr/bin/env python3
"""Run a shell script on the maintenance VM through the Azure run-command API.

This is how a Claude Code session — or any host with the service principal and
no network path to the estate — reaches the databases. Nothing here opens a
socket to your infrastructure: it is a control-plane call to
``management.azure.com``, and the VM's own guest agent collects the script and
runs it. The VM resolves database credentials from Key Vault through its
managed identity, so no database password is needed here, ever.

There is no ``az`` CLI on a session host, so this makes the same calls by hand.

    python tools/run_on_vm.py 'hostname; id'
    python tools/run_on_vm.py -            # read the script from stdin
    python tools/run_on_vm.py --fetch /tmp/report.b64 --out report.b64

Environment:
    ARM_TENANT_ID, ARM_CLIENT_ID, ARM_CLIENT_SECRET, ARM_SUBSCRIPTION_ID
    TRD365_RG   (default: trd365-maintenance)
    TRD365_VM   (default: trd365-maint-vm)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "2024-07-01"
#: Measured, not documented: the run-command response truncates one message at
#: about 4 KiB. Anything larger has to come back in pieces.
CHUNK = 3900
RETRIES = 5


def _token() -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["ARM_CLIENT_ID"],
            "client_secret": os.environ["ARM_CLIENT_SECRET"],
            "scope": "https://management.azure.com/.default",
        }
    ).encode()
    url = f"https://login.microsoftonline.com/{os.environ['ARM_TENANT_ID']}/oauth2/v2.0/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=60) as r:
        return json.load(r)["access_token"]


def _vm_url() -> str:
    sub = os.environ["ARM_SUBSCRIPTION_ID"]
    rg = os.environ.get("TRD365_RG", "trd365-maintenance")
    vm = os.environ.get("TRD365_VM", "trd365-maint-vm")
    return (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.Compute/virtualMachines/{vm}/runCommand?api-version={API}"
    )


def run(script: str, timeout: int = 2400) -> tuple[int, str]:
    """Execute ``script`` on the VM and return ``(exit_status, stdout)``.

    A 409 means another run-command is still executing — the VM takes one at a
    time — so it is worth waiting rather than failing.
    """
    tok = _token()
    body = {"commandId": "RunShellScript", "script": script.splitlines()}
    req = urllib.request.Request(_vm_url(), data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {tok}")
    req.add_header("Content-Type", "application/json")

    for attempt in range(RETRIES):
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 409 or attempt == RETRIES - 1:
                raise
            time.sleep(20 * (attempt + 1))  # someone else's script is still running
    poll = resp.headers.get("Azure-AsyncOperation") or resp.headers.get("Location")

    # The script can outlast the token, and the proxy in front of a session host
    # drops long polls, so refresh and retry rather than lose a finished run.
    deadline, refreshed = time.time() + timeout, time.time()
    while time.time() < deadline:
        time.sleep(15)
        if time.time() - refreshed > 1800:
            tok, refreshed = _token(), time.time()
        preq = urllib.request.Request(poll)
        preq.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(preq, timeout=60) as r:
                payload = json.load(r)
        except (urllib.error.URLError, ConnectionError):
            continue  # the poll dropped; the script on the VM is unaffected
        status = payload.get("status", "")
        if status in ("InProgress", "Running", "Accepted"):
            continue
        out = "\n".join(
            m.get("message", "")
            for m in payload.get("properties", {}).get("output", {}).get("value", [])
        )
        return (0 if status == "Succeeded" else 1), out
    return 2, "timed out waiting for the run-command"


def fetch(remote: str, out_path: str) -> None:
    """Retrieve a file from the VM in stdout-sized pieces.

    The only channel out of a run-command is its stdout, so a report has to be
    gzipped, base64'd and read back a slice at a time. Write it on the VM with:
    ``base64.b64encode(gzip.compress(raw))``.
    """
    status, size_out = run(f"wc -c < {remote}")
    if status:
        raise SystemExit(f"could not size {remote}: {size_out}")
    size = int(next(line for line in size_out.splitlines() if line.strip().isdigit()))
    pieces = -(-size // CHUNK)
    with open(out_path, "w", encoding="utf-8") as fh:
        for n in range(pieces):
            expr = f"d=open('{remote}').read(); print(d[{n}*{CHUNK}:({n}+1)*{CHUNK}])"
            status, text = run(f'python3 -c "{expr}"')
            if status:
                raise SystemExit(f"chunk {n} failed: {text}")
            body = text.split("[stdout]", 1)[-1].split("[stderr]", 1)[0]
            fh.write(body.strip())
            print(f"  {n + 1}/{pieces}", file=sys.stderr)
    print(f"wrote {out_path}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("script", nargs="?", help="script text, or - to read stdin")
    ap.add_argument("--fetch", metavar="REMOTE", help="retrieve a file from the VM")
    ap.add_argument("--out", metavar="PATH", help="where --fetch writes")
    args = ap.parse_args()

    if args.fetch:
        fetch(args.fetch, args.out or os.path.basename(args.fetch))
        return 0
    if not args.script:
        ap.error("give a script, or --fetch")
    script = sys.stdin.read() if args.script == "-" else args.script
    status, out = run(script)
    print(out)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
