"""
Run the real utilities and capture what they produce, for the preview page.

Every figure the page shows comes from here. The utilities run against the
packages' own test doubles, because no session can reach a database — which is
exactly what the page says about itself.

The imports below deliberately come after the environment is redirected into a
temporary directory: the model store, checkpoint store and audit sink all read
their locations at import time, and a preview must not write into anyone's real
state. Hence the E402 suppression.
"""
# ruff: noqa: E402

import contextlib
import glob
import importlib.util
import io
import json
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(
    TRD365_MODEL_DIR=tmp + "/model",
    TRD365_STATE_DIR=tmp + "/state",
    TRD365_AUDIT_DIR=tmp + "/audit",
)
OUT = sys.argv[1]


def load(name, path):
    """Import a package's test doubles without installing them."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

afakes = load("afakes", "packages/trd365-analysis/tests/fakes.py")
pfakes = load("pfakes", "packages/trd365-data-purge/tests/fakes.py")

from trd365_core.registry import load_installed_utilities, registry
from trd365_core.audit import MemoryAuditSink
from trd365_core.environments import Environment, configuration_status
load_installed_utilities()

data = {}
data["utilities"] = registry.to_dict()
data["environments"] = [
    {"name": e.value, "workspace": e.platform_workspace,
     "is_production": e.is_production,
     "status": {k: v for k, v in configuration_status(e).items()}}
    for e in Environment
]

# ---- real data-model analysis run -----------------------------------------
from trd365_analysis import cli as acli, reporting as arep
db = afakes.FakeDatabase()
for schema in ("trd365_00042", "trd365_00117"):
    db.tables[("orgdb", schema, "project")] = afakes.table(["rid", "account_rid"], [
        {"rid": "p1", "account_rid": "ACCT-1"}])
    db.tables[("orgdb", schema, "cases")] = afakes.table(["rid", "account_rid"], [])
    db.tables[("orgdb", schema, "project_history")] = afakes.table(["rid", "project_rid"], [
        {"rid": "h1", "project_rid": "p1"}, {"rid": "h2", "project_rid": "DELETED-2024"},
        {"rid": "h3", "project_rid": "DELETED-2024"}])
    db.tables[("orgdb", schema, "case_history")] = afakes.table(["rid", "case_rid"], [
        {"rid": "c1", "case_rid": "GONE-119"}])
    db.tables[("orgdb", schema, "signoff_details")] = afakes.table(["rid", "projekt_rid"], [])
db.tables[("maindb", "trd365", "account")] = afakes.table(["rid"], [{"rid": "ACCT-1"}])

asink = MemoryAuditSink()
code = acli.run(["--env", "dev", "--apply", "--out-dir", tmp+"/reports"],
                pool_factory=lambda _e, log=None: afakes.FakePool(db), audit_sink=asink)
data["analysis_exit"] = code

from trd365_core.model_snapshot import FileModelStore
snap = FileModelStore().latest(Environment.DEV)
data["model"] = {"version": snap.version, "fingerprint": snap.fingerprint,
                 "generated_at": snap.generated_at, "summary": snap.summary(),
                 "schemas": snap.tenant_schemas,
                 "deviations": arep.deviation_counts(snap)}

txt = sorted(glob.glob(tmp+"/reports/data_model_*.txt"))[-1]
data["analysis_report"] = open(txt).read()

# ---- real purge dry run ----------------------------------------------------
from trd365_data_purge import cli as pcli
from trd365_data_purge.account import __main__ as account
conn = pfakes.FakeConnection({
    ("trd365_00042", "cases"): pfakes.table(["rid","account_rid"],
        [{"rid": f"c{i}", "account_rid": "ACCT-1"} for i in range(37)]),
    ("trd365_00042", "project"): pfakes.table(["rid","account_rid"],
        [{"rid": f"p{i}", "account_rid": "ACCT-1"} for i in range(12)]),
    ("trd365_00042", "project_fiscal"): pfakes.table(["rid","account_rid"],
        [{"rid": f"f{i}", "account_rid": "ACCT-1"} for i in range(28)]),
    ("trd365_00042", "resources"): pfakes.table(["rid","account_rid"],
        [{"rid": f"r{i}", "account_rid": "ACCT-1"} for i in range(9)]),
    ("trd365_00042", "attachments"): pfakes.table(["rid","account_rid"],
        [{"rid": f"a{i}", "account_rid": "ACCT-1"} for i in range(153)]),
})
pool = pfakes.FakePool({"orgdb": conn,
    "maindb": pfakes.AccountDirectory(
        {"ACCT-1": ("ACC-00042", "store_in_own", None)},
        {("trd365", "account"): pfakes.table(["rid","r_number"], [{"rid":"ACCT-1"}]),
         ("trd365", "case_summary"): pfakes.table(["rid","account_rid"],
             [{"rid": f"s{i}", "account_rid": "ACCT-1"} for i in range(37)]),
         ("trd365", "project_summary"): pfakes.table(["rid","account_rid","project_rid"],
             [{"rid": f"ps{i}", "account_rid": "ACCT-1"} for i in range(12)]),
         ("trd365", "account_fiscal_summary"): pfakes.table(["rid","account_rid"],
             [{"rid": f"af{i}", "account_rid": "ACCT-1"} for i in range(4)])}),
    "trd365ai": pfakes.FakeConnection({})})
psink = MemoryAuditSink()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    pcode = pcli.run(entity="account", description="purge", resolver=account.resolve,
        entity_rid=account.entity_rid, configure=account.configure,
        argv=["--env","dev","--account-rid","ACCT-1","--out-dir",tmp+"/reports"],
        pool_factory=lambda _e, log=None: pool, audit_sink=psink)
data["purge_exit"] = pcode
data["purge_console"] = buf.getvalue()
ptxt = sorted(glob.glob(tmp+"/reports/account_*.txt"))[-1]
data["purge_report"] = open(ptxt).read()

data["audit"] = [
    {k: v for k, v in vars(r).items()}
    for r in (asink.records + psink.records)
]

json.dump(data, open(OUT, "w"), indent=2, default=str)
print(f"wrote {OUT}")
for k, v in data.items():
    print(f"  {k}: {len(v) if hasattr(v,'__len__') else v}")
