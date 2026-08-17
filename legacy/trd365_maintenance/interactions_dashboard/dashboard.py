#!/usr/bin/env python3
"""Interactions metrics dashboard — pull from DB, host locally.

Summarizes interaction metrics across ALL accounts (all trd365_<nnnnn> org tenant
schemas) by RESPONSE RECEIVED DATE, defined as interactions.response_updated_on
(the populated response timestamp; interaction_send_history.response_received_datetime
is sparse and not used). Account names come from maindb trd365.account.

What it does:
  1. Connects to org + main (reusing engine/db.py: SSH tunnels, retry/backoff).
  2. Aggregates per (tenant, account, date) for responses-received and sent.
  3. Renders a self-contained HTML dashboard (no CDN — vanilla SVG charts).
  4. Serves it on http://127.0.0.1:<port> and opens your browser.

Usage:
    python dashboard.py                    # pull, build, serve on :8000, open browser
    python dashboard.py --port 8080
    python dashboard.py --build-only       # just write the HTML, don't serve
    python dashboard.py --date-field response_submitted_on
    python dashboard.py --no-open          # serve but don't auto-open browser
"""
import argparse
import functools
import http.server
import json
import socketserver
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_SRC = HERE.parent / "reference_table_corrections"  # reuse the proven engine + config
sys.path.insert(0, str(ENGINE_SRC))
sys.path.insert(0, str(HERE))

from engine import db  # noqa: E402
from psycopg2 import sql as _sql  # noqa: E402

CONFIG = ENGINE_SRC / "config" / "db_config.json"
MAIN_SCHEMA = "trd365"
DATE_FIELDS = ("response_updated_on", "response_submitted_on")


def _fetch(pool, dbk, query, params=None, timeout=120):
    """Read query with a simple execute (aggregates are cheap here)."""
    conn = pool.get(dbk)
    cur = conn.cursor()
    try:
        cur.execute(query, params) if params is not None else cur.execute(query)
        rows = cur.fetchall()
        conn.rollback()
        return rows
    finally:
        cur.close()


def org_schemas(pool):
    return [r[0] for r in _fetch(pool, "orgdb",
        "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'trd365\\_%' ESCAPE '\\' "
        "AND nspname NOT LIKE '%backup%' ORDER BY 1")]


def account_names(pool):
    rows = _fetch(pool, "maindb",
        _sql.SQL("SELECT rid, account_name FROM {}.account").format(_sql.Identifier(MAIN_SCHEMA)))
    return {r[0]: (r[1] or "").strip() for r in rows}


def pull(pool, date_field, log=print):
    """Return aggregated facts: responses-received and sent, per (tenant, account, date)."""
    if date_field == "response_submitted_on":
        # response_submitted_on is varchar; cast defensively
        resp_expr = "NULLIF(response_submitted_on,'')::timestamptz"
    else:
        resp_expr = "response_updated_on"

    acct = account_names(pool)
    log(f"[main] loaded {len(acct)} account names")

    schemas = org_schemas(pool)
    resp_facts = defaultdict(int)   # (tenant, account_rid, date) -> count
    sent_facts = defaultdict(int)
    totals = dict(interactions=0, sent=0, responses=0)
    per_tenant = {}

    for i, S in enumerate(schemas, 1):
        try:
            tot = _fetch(pool, "orgdb", _sql.SQL(
                "SELECT count(*), count(sent_on_datetime), count(" + resp_expr + ") "
                "FROM {}.interactions WHERE COALESCE(is_deleted,false)=false"
            ).format(_sql.Identifier(S)))[0]
            per_tenant[S] = dict(interactions=tot[0], sent=tot[1], responses=tot[2])
            totals["interactions"] += tot[0]; totals["sent"] += tot[1]; totals["responses"] += tot[2]

            if tot[2]:  # responses received, grouped by account + response date (UTC)
                for arid, d, n in _fetch(pool, "orgdb", _sql.SQL(
                    "SELECT account_rid, (" + resp_expr + " AT TIME ZONE 'UTC')::date, count(*) "
                    "FROM {}.interactions WHERE COALESCE(is_deleted,false)=false "
                    "AND " + resp_expr + " IS NOT NULL GROUP BY 1,2"
                ).format(_sql.Identifier(S))):
                    resp_facts[(S, arid, d.isoformat())] += n
            if tot[1]:  # sent, grouped by account + sent date (UTC)
                for arid, d, n in _fetch(pool, "orgdb", _sql.SQL(
                    "SELECT account_rid, (sent_on_datetime AT TIME ZONE 'UTC')::date, count(*) "
                    "FROM {}.interactions WHERE COALESCE(is_deleted,false)=false "
                    "AND sent_on_datetime IS NOT NULL GROUP BY 1,2"
                ).format(_sql.Identifier(S))):
                    sent_facts[(S, arid, d.isoformat())] += n
            log(f"[{i:>2}/{len(schemas)}] {S}: interactions={tot[0]:>5} sent={tot[1]:>5} responses={tot[2]:>5}")
        except Exception as exc:
            log(f"[{i:>2}/{len(schemas)}] {S}: ERROR {type(exc).__name__}: {str(exc).strip()[:70]} — skipped")
            pool.drop_all()

    def factlist(fd):
        out = []
        for (tenant, arid, d), n in fd.items():
            nm = acct.get(arid) or (f"({arid[:12]}…)" if arid else "(no account)")
            out.append({"tenant": tenant, "account_rid": arid or "", "account": nm, "date": d, "count": n})
        return out

    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "date_field": date_field,
        "totals": totals,
        "per_tenant": per_tenant,
        "responses": factlist(resp_facts),
        "sent": factlist(sent_facts),
    }


# ── HTML (self-contained; vanilla JS + SVG, no external assets) ────────────────
HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interactions Metrics — by Response Received Date</title>
<style>
:root{
  --bg:#0f1420; --panel:#171d2c; --panel2:#1e2536; --ink:#e7ecf5; --mut:#94a3b8;
  --line:#2a3145; --accent:#5b9dff; --accent2:#34d399; --warn:#fbbf24; --bar:#5b9dff;
}
@media (prefers-color-scheme: light){:root{
  --bg:#f4f6fb; --panel:#ffffff; --panel2:#f0f3fa; --ink:#0f172a; --mut:#5b6577;
  --line:#e2e8f0; --accent:#2563eb; --accent2:#059669; --warn:#d97706; --bar:#2563eb;}}
*{box-sizing:border-box} html,body{margin:0}
body{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg); color:var(--ink); padding:22px;}
h1{font-size:20px;margin:0 0 2px} .sub{color:var(--mut);font-size:12px;margin-bottom:18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:650} .kpi .l{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-top:2px}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:16px}
select,input{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:13px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px}
.card h2{font-size:13px;margin:0 0 12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.grid2{display:grid;grid-template-columns:1fr;gap:16px} @media(min-width:960px){.grid2{grid-template-columns:1.4fr 1fr}}
.legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin-bottom:6px}
.legend b{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
table{width:100%;border-collapse:collapse;font-size:13px} th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;cursor:pointer;user-select:none} td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{max-height:360px;overflow:auto} .barrow{display:flex;align-items:center;gap:8px;margin:5px 0}
.barrow .nm{width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.barrow .track{flex:1;background:var(--panel2);border-radius:5px;height:16px;position:relative}
.barrow .fill{background:var(--bar);height:100%;border-radius:5px} .barrow .n{width:56px;text-align:right;font-variant-numeric:tabular-nums;font-size:12px}
svg{width:100%;height:auto;display:block} .tip{fill:var(--ink)} .muted{color:var(--mut)}
.foot{color:var(--mut);font-size:11px;margin-top:8px}
</style></head><body>
<h1>Interactions Metrics — by Response Received Date</h1>
<div class="sub" id="sub"></div>

<div class="kpis" id="kpis"></div>

<div class="controls">
  <label>Tenant <select id="fTenant"><option value="">All tenants</option></select></label>
  <label>Account <select id="fAccount"><option value="">All accounts</option></select></label>
  <label>From <input type="date" id="fFrom"></label>
  <label>To <input type="date" id="fTo"></label>
  <button id="reset" style="background:var(--panel2)">Reset</button>
</div>

<div class="card">
  <h2>Responses received per day</h2>
  <div class="legend"><span><b style="background:var(--accent)"></b>Responses received</span>
    <span><b style="background:var(--accent2)"></b>Sent</span></div>
  <div id="tsChart"></div>
</div>

<div class="grid2">
  <div class="card"><h2>Top accounts by responses received</h2><div id="acctBars"></div></div>
  <div class="card"><h2>By tenant</h2><div id="tenantBars"></div></div>
</div>

<div class="card">
  <h2>Daily breakdown</h2>
  <div class="scroll"><table id="tbl"><thead><tr>
    <th data-k="date">Response date</th>
    <th class="num" data-k="responses">Responses</th>
    <th class="num" data-k="sent">Sent</th>
    <th class="num" data-k="accounts">Accounts</th>
  </tr></thead><tbody></tbody></table></div>
  <div class="foot">Dates are UTC. “Response received date” = <code id="df"></code>. Sent series uses sent_on_datetime.</div>
</div>

<script>
const DATA = __DATA__;
const $=s=>document.querySelector(s), fmt=n=>n.toLocaleString();
document.getElementById('sub').textContent =
  `Generated ${DATA.generated_utc} · ${DATA.responses.length?'':'no responses in range · '}`+
  `${Object.keys(DATA.per_tenant).length} tenant schemas scanned`;
document.getElementById('df').textContent = DATA.date_field;

// populate filters
const tenants=[...new Set([...DATA.responses,...DATA.sent].map(r=>r.tenant))].sort();
const accounts=[...new Set([...DATA.responses,...DATA.sent].map(r=>r.account))].sort();
for(const t of tenants) fTenant.add(new Option(t,t));
for(const a of accounts) fAccount.add(new Option(a,a));

function state(){return{tenant:fTenant.value,account:fAccount.value,from:fFrom.value,to:fTo.value};}
function match(r,s){return (!s.tenant||r.tenant===s.tenant)&&(!s.account||r.account===s.account)
  &&(!s.from||r.date>=s.from)&&(!s.to||r.date<=s.to);}

function agg(){
  const s=state();
  const resp=DATA.responses.filter(r=>match(r,s)), sent=DATA.sent.filter(r=>match(r,s));
  const byDate={}, acctSet={}, byAcct={}, byTenant={};
  for(const r of resp){(byDate[r.date]=byDate[r.date]||{responses:0,sent:0,accs:new Set()});
    byDate[r.date].responses+=r.count; byDate[r.date].accs.add(r.account);
    byAcct[r.account]=(byAcct[r.account]||0)+r.count; byTenant[r.tenant]=(byTenant[r.tenant]||0)+r.count;}
  for(const r of sent){(byDate[r.date]=byDate[r.date]||{responses:0,sent:0,accs:new Set()}); byDate[r.date].sent+=r.count;}
  const totResp=resp.reduce((a,b)=>a+b.count,0), totSent=sent.reduce((a,b)=>a+b.count,0);
  const nAcc=new Set(resp.map(r=>r.account)).size, nTen=new Set(resp.map(r=>r.tenant)).size;
  return {byDate,byAcct,byTenant,totResp,totSent,nAcc,nTen,dates:Object.keys(byDate).sort()};
}

function kpis(a){
  const days=a.dates.length, rate=a.totSent? (100*a.totResp/a.totSent):0;
  const items=[['Responses received',fmt(a.totResp)],['Interactions sent',fmt(a.totSent)],
    ['Response rate',rate.toFixed(1)+'%'],['Accounts responding',fmt(a.nAcc)],
    ['Tenants',fmt(a.nTen)],['Avg responses / active day',days?(a.totResp/days).toFixed(1):'0']];
  $('#kpis').innerHTML=items.map(([l,v])=>`<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}

function tsChart(a){
  const W=920,H=260,pl=44,pr=14,pt=14,pb=42, iw=W-pl-pr, ih=H-pt-pb;
  const dates=a.dates; if(!dates.length){$('#tsChart').innerHTML='<div class="muted">No data in range.</div>';return;}
  const max=Math.max(1,...dates.map(d=>Math.max(a.byDate[d].responses,a.byDate[d].sent)));
  const x=i=>pl+(dates.length===1?iw/2:iw*i/(dates.length-1)), y=v=>pt+ih-ih*v/max;
  const line=(key,col)=>{let p='';dates.forEach((d,i)=>{p+=(i?'L':'M')+x(i).toFixed(1)+' '+y(a.byDate[d][key]).toFixed(1)+' ';});
    return `<path d="${p}" fill="none" stroke="${col}" stroke-width="2"/>`+
      dates.map((d,i)=>`<circle cx="${x(i).toFixed(1)}" cy="${y(a.byDate[d][key]).toFixed(1)}" r="2.6" fill="${col}"><title>${d}\n${key}: ${a.byDate[d][key]}</title></circle>`).join('');};
  const ticks=4, gy=[...Array(ticks+1)].map((_,i)=>{const v=Math.round(max*i/ticks);return`<g><line x1="${pl}" y1="${y(v)}" x2="${W-pr}" y2="${y(v)}" stroke="var(--line)"/><text x="${pl-6}" y="${y(v)+3}" text-anchor="end" font-size="10" fill="var(--mut)">${v}</text></g>`;}).join('');
  const step=Math.ceil(dates.length/8);
  const gx=dates.map((d,i)=>i%step? '' :`<text x="${x(i)}" y="${H-pb+16}" text-anchor="middle" font-size="10" fill="var(--mut)">${d.slice(5)}</text>`).join('');
  $('#tsChart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${gy}${gx}
    ${line('sent','var(--accent2)')}${line('responses','var(--accent)')}</svg>`;
}

function bars(el,obj,color){
  const rows=Object.entries(obj).sort((x,y)=>y[1]-x[1]).slice(0,12);
  const max=Math.max(1,...rows.map(r=>r[1]));
  el.innerHTML=rows.length? rows.map(([k,v])=>`<div class="barrow"><div class="nm" title="${k}">${k}</div>
    <div class="track"><div class="fill" style="width:${100*v/max}%;background:${color}"></div></div>
    <div class="n">${fmt(v)}</div></div>`).join('') : '<div class="muted">No data.</div>';
}

let sortK='date',sortDir=-1;
function table(a){
  const rows=a.dates.map(d=>({date:d,responses:a.byDate[d].responses,sent:a.byDate[d].sent,accounts:a.byDate[d].accs.size}));
  rows.sort((x,y)=>{const A=x[sortK],B=y[sortK];return (A<B?-1:A>B?1:0)*sortDir;});
  $('#tbl tbody').innerHTML=rows.map(r=>`<tr><td>${r.date}</td><td class="num">${fmt(r.responses)}</td>
    <td class="num">${fmt(r.sent)}</td><td class="num">${fmt(r.accounts)}</td></tr>`).join('')
    ||'<tr><td colspan="4" class="muted">No data in range.</td></tr>';
}
document.querySelectorAll('#tbl th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;
  sortDir=(sortK===k)?-sortDir:1; sortK=k; render();});

function render(){const a=agg(); kpis(a); tsChart(a);
  bars($('#acctBars'),a.byAcct,'var(--accent)'); bars($('#tenantBars'),a.byTenant,'var(--warn)'); table(a);}
[fTenant,fAccount,fFrom,fTo].forEach(e=>e.onchange=render);
$('#reset').onclick=()=>{fTenant.value='';fAccount.value='';fFrom.value='';fTo.value='';render();};
render();
</script></body></html>"""


def build_html(data):
    return HTML_TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))


def serve(directory, port, open_browser, log=print):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/index.html"
        log(f"\nServing dashboard at {url}\n(Ctrl-C to stop)")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log("\nStopped.")


def main():
    ap = argparse.ArgumentParser(description="Interactions metrics dashboard (pull + host locally).")
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--date-field", choices=DATE_FIELDS, default="response_updated_on",
                    help="Field treated as 'response received date'. Default: response_updated_on.")
    ap.add_argument("--out-dir", type=Path, default=HERE / "site")
    ap.add_argument("--build-only", action="store_true", help="Write HTML but do not serve.")
    ap.add_argument("--no-open", action="store_true", help="Serve without opening the browser.")
    args = ap.parse_args()

    if not args.config.exists():
        sys.exit(f"Config not found: {args.config}")

    print("=" * 78)
    print("Interactions Metrics Dashboard")
    print(f"date field : {args.date_field}")
    print("=" * 78)

    pool = db.ConnectionPool(db.load_config(args.config))
    try:
        data = pull(pool, args.date_field)
    finally:
        pool.close_all()
        print("[cleanup] connections + tunnels closed.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "index.html"
    out.write_text(build_html(data), encoding="utf-8")
    # also drop the raw aggregated data next to it for reuse
    (args.out_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    t = data["totals"]
    print(f"\nBuilt {out}")
    print(f"  totals: interactions={t['interactions']}  sent={t['sent']}  responses={t['responses']}")
    print(f"  facts : {len(data['responses'])} response rows, {len(data['sent'])} sent rows")

    if args.build_only:
        print("\n--build-only: not serving. Open the file above or run without the flag to host.")
        return
    serve(args.out_dir, args.port, not args.no_open)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
