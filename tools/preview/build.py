"""Render the preview page from real system output."""
import html
import json
import sys

data = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
e = html.escape

utils = data["utilities"]
model = data["model"]
audit = data["audit"]
# configuration_status returns the whole estate; take it once.
status = data["environments"][0]["status"]
workspaces = {x["name"]: x["workspace"] for x in data["environments"]}
prod = {x["name"]: x["is_production"] for x in data["environments"]}

IMPACT = {
    "destructive": ("danger", "Destructive"),
    "writes": ("warn", "Writes"),
    "read-only": ("ok", "Read only"),
}


def env_card(name):
    dbs = status[name]
    ready = sum(1 for v in dbs.values() if v)
    total = len(dbs)
    state = "ok" if ready == total else ("warn" if ready else "idle")
    label = "Configured" if ready == total else (f"{ready}/{total} configured" if ready else "Credentials pending")
    dots = "".join(
        f'<span class="db {"on" if ok else "off"}"><i></i>{e(k)}</span>' for k, ok in dbs.items()
    )
    return f'''<article class="env s-{state}">
  <header><h3>{e(name)}</h3>{'<span class="tag danger">production</span>' if prod[name] else ''}</header>
  <p class="readout">{e(label)}</p>
  <div class="dbs">{dots}</div>
  <p class="foot">platform workspace <code>{e(workspaces[name])}</code></p>
</article>'''


def util_card(u):
    tone, label = IMPACT[u["impact"]]
    params = "".join(
        f'<li><code>{e(p["flag"])}</code>{" <em>required</em>" if p["required"] else ""}'
        f'<span>{e(p["help"])}</span></li>'
        for p in u["parameters"]
    )
    dbs = "".join(f'<span class="chip">{e(d)}</span>' for d in u["databases"])
    return f'''<article class="util t-{tone}">
  <header>
    <div><h3>{e(u["title"])}</h3><code class="id">{e(u["id"])}</code></div>
    <span class="tag {tone}">{e(label)}</span>
  </header>
  <p>{e(u["description"])}</p>
  <div class="meta">
    <div><span class="lbl">Databases</span><div class="chips">{dbs}</div></div>
    <div><span class="lbl">Approval in prod</span>
      <div>{'Required — second approver' if u["requires_approval_in_prod"] else 'Not required'}</div></div>
    <div><span class="lbl">Invoked as</span><code>python -m {e(u["module"])}</code></div>
  </div>
  <details><summary>{len(u["parameters"])} parameters</summary><ul class="params">{params}</ul></details>
</article>'''


def audit_row(r):
    mode = "apply" if r["applied"] else "dry-run"
    notes = "<br>".join(e(n) for n in r["notes"])
    return f'''<tr>
  <td><code>{e(r["utility"])}</code></td>
  <td>{e(r["environment"])}</td>
  <td><span class="tag {"warn" if r["applied"] else "idle"}">{mode}</span></td>
  <td><span class="tag ok">{e(r["outcome"])}</span></td>
  <td class="num">{e(r["started_at"][11:19])}</td>
  <td class="notes">{notes}</td>
</tr>'''


page = f'''<title>Certainti Maintenance Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=Public+Sans:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap">
<style>
:root {{
  --ground:#F1F4F4; --surface:#FFFFFF; --sunk:#E7ECEC;
  --ink:#0D1719; --body:#33474A; --muted:#5F7175; --line:#D6E0E0;
  --accent:#0B6E63; --accent-soft:#E2F0EE;
  --ok:#1A7F4B; --warn:#A65A07; --danger:#B3261E; --idle:#69787B;
  --ok-bg:#E4F2EA; --warn-bg:#FBEEE0; --danger-bg:#FBE7E5; --idle-bg:#E9EEEE;
  --term:#0C1618; --term-ink:#CBDCDA;
  --radius:10px;
  --display:"Archivo",system-ui,sans-serif;
  --text:"Public Sans",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#080F11; --surface:#0F1A1D; --sunk:#0A1315;
    --ink:#E1EBEB; --body:#B4C6C7; --muted:#8A9C9E; --line:#203034;
    --accent:#35C7B4; --accent-soft:#10312E;
    --ok:#4ECB8B; --warn:#E0A45C; --danger:#F0837A; --idle:#7D8F92;
    --ok-bg:#0F2A1E; --warn-bg:#2C2113; --danger-bg:#2E1917; --idle-bg:#172124;
    --term:#060D0F; --term-ink:#B9CDCB;
  }}
}}
:root[data-theme="dark"] {{
  --ground:#080F11; --surface:#0F1A1D; --sunk:#0A1315;
  --ink:#E1EBEB; --body:#B4C6C7; --muted:#8A9C9E; --line:#203034;
  --accent:#35C7B4; --accent-soft:#10312E;
  --ok:#4ECB8B; --warn:#E0A45C; --danger:#F0837A; --idle:#7D8F92;
  --ok-bg:#0F2A1E; --warn-bg:#2C2113; --danger-bg:#2E1917; --idle-bg:#172124;
  --term:#060D0F; --term-ink:#B9CDCB;
}}

*{{box-sizing:border-box}}
body{{
  margin:0; background:var(--ground); color:var(--body);
  font-family:var(--text); font-size:15px; line-height:1.6;
  -webkit-font-smoothing:antialiased;
}}
.wrap{{max-width:1120px; margin:0 auto; padding:0 24px 96px}}
h1,h2,h3{{font-family:var(--display); color:var(--ink); text-wrap:balance; margin:0}}
h1{{font-size:clamp(28px,4vw,42px); font-weight:700; letter-spacing:-.02em}}
h2{{font-size:20px; font-weight:600; letter-spacing:-.01em}}
h3{{font-size:16px; font-weight:600}}
code,.num{{font-family:var(--mono); font-variant-numeric:tabular-nums}}

/* ---- masthead ---- */
.mast{{border-bottom:1px solid var(--line); background:var(--surface)}}
.mast .wrap{{padding-block:32px 28px; display:flex; flex-direction:column; gap:14px}}
.eyebrow{{
  font-family:var(--display); font-size:11px; font-weight:600; letter-spacing:.14em;
  text-transform:uppercase; color:var(--accent); margin:0;
}}
.lede{{max-width:62ch; margin:0; font-size:16.5px}}

/* ---- honesty banner ---- */
.notice{{
  margin:24px 0 0; padding:16px 18px; border-radius:var(--radius);
  background:var(--warn-bg); border:1px solid color-mix(in srgb, var(--warn) 32%, transparent);
  display:flex; gap:14px; align-items:flex-start;
}}
.notice .bar{{width:3px; align-self:stretch; background:var(--warn); border-radius:2px; flex:none}}
.notice p{{margin:0 0 6px}}
.notice p:last-child{{margin:0}}
.notice strong{{color:var(--ink); font-family:var(--display); font-weight:600}}

section{{margin-top:52px}}
.shead{{display:flex; align-items:baseline; gap:14px; margin-bottom:6px; flex-wrap:wrap}}
.shead p{{margin:0; color:var(--muted); font-size:14px}}
.grid{{display:grid; gap:14px; margin-top:20px}}
.g4{{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}}
.g2{{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}}

/* ---- cards ---- */
article{{
  background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); padding:18px; position:relative; overflow:hidden;
}}
article header{{display:flex; justify-content:space-between; align-items:flex-start; gap:12px}}
article p{{margin:10px 0 0; font-size:14.5px}}

.env::before{{content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--idle)}}
.env.s-ok::before{{background:var(--ok)}}
.env.s-warn::before{{background:var(--warn)}}
.env h3{{text-transform:uppercase; letter-spacing:.08em; font-size:13px}}
.readout{{font-family:var(--display); font-size:17px; color:var(--ink); font-weight:600}}
.dbs{{display:flex; flex-wrap:wrap; gap:6px; margin-top:12px}}
.db{{
  display:inline-flex; align-items:center; gap:6px; font-family:var(--mono);
  font-size:11.5px; padding:3px 8px; border-radius:99px; background:var(--sunk); color:var(--muted);
}}
.db i{{width:6px; height:6px; border-radius:99px; background:var(--idle); flex:none}}
.db.on i{{background:var(--ok)}}
.foot{{font-size:12.5px; color:var(--muted); margin-top:12px}}
.foot code{{font-size:12px}}

.util::before{{content:""; position:absolute; inset:0 auto 0 0; width:3px}}
.util.t-danger::before{{background:var(--danger)}}
.util.t-warn::before{{background:var(--warn)}}
.util.t-ok::before{{background:var(--ok)}}
.id{{font-size:12px; color:var(--muted); display:block; margin-top:3px}}
.meta{{display:grid; gap:12px; margin-top:16px; padding-top:14px; border-top:1px solid var(--line)}}
.lbl{{
  display:block; font-family:var(--display); font-size:10.5px; font-weight:600;
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted); margin-bottom:4px;
}}
.meta > div > div{{font-size:14px; color:var(--ink)}}
.meta code{{font-size:12.5px}}
.chips{{display:flex; gap:5px; flex-wrap:wrap}}
.chip{{font-family:var(--mono); font-size:11.5px; padding:2px 7px; border-radius:4px;
  background:var(--accent-soft); color:var(--accent)}}
details{{margin-top:14px; border-top:1px solid var(--line); padding-top:12px}}
summary{{cursor:pointer; font-size:13px; color:var(--accent); font-weight:500}}
summary:focus-visible{{outline:2px solid var(--accent); outline-offset:3px; border-radius:3px}}
.params{{list-style:none; margin:12px 0 0; padding:0; display:grid; gap:9px}}
.params li{{display:grid; gap:2px; font-size:13px}}
.params code{{font-size:12.5px; color:var(--ink)}}
.params em{{color:var(--danger); font-style:normal; font-size:11px; font-family:var(--display);
  font-weight:600; letter-spacing:.06em; text-transform:uppercase; margin-left:6px}}
.params span{{color:var(--muted)}}

.tag{{
  font-family:var(--display); font-size:10.5px; font-weight:600; letter-spacing:.07em;
  text-transform:uppercase; padding:3px 8px; border-radius:4px; white-space:nowrap; flex:none;
  background:var(--idle-bg); color:var(--idle);
}}
.tag.ok{{background:var(--ok-bg); color:var(--ok)}}
.tag.warn{{background:var(--warn-bg); color:var(--warn)}}
.tag.danger{{background:var(--danger-bg); color:var(--danger)}}

/* ---- stat strip ---- */
.stats{{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:var(--radius); overflow:hidden}}
.stat{{background:var(--surface); padding:16px 18px}}
.stat .v{{font-family:var(--display); font-size:26px; font-weight:700; color:var(--ink);
  font-variant-numeric:tabular-nums; line-height:1.1}}
.stat .k{{font-size:12.5px; color:var(--muted); margin-top:3px}}

/* ---- terminal ---- */
.term{{margin-top:20px; border-radius:var(--radius); overflow:hidden; border:1px solid var(--line)}}
.tabs{{display:flex; background:var(--sunk); border-bottom:1px solid var(--line); overflow-x:auto}}
.tabs button{{
  font-family:var(--display); font-size:12.5px; font-weight:600; letter-spacing:.03em;
  padding:11px 16px; background:none; border:0; border-bottom:2px solid transparent;
  color:var(--muted); cursor:pointer; white-space:nowrap;
}}
.tabs button[aria-selected="true"]{{color:var(--ink); border-bottom-color:var(--accent)}}
.tabs button:focus-visible{{outline:2px solid var(--accent); outline-offset:-2px}}
.term pre{{
  margin:0; padding:20px; background:var(--term); color:var(--term-ink);
  font-family:var(--mono); font-size:12.5px; line-height:1.65;
  overflow-x:auto; max-height:520px; overflow-y:auto;
}}
.term pre[hidden]{{display:none}}

/* ---- table ---- */
.tablewrap{{overflow-x:auto; border:1px solid var(--line); border-radius:var(--radius);
  background:var(--surface); margin-top:20px}}
table{{width:100%; border-collapse:collapse; font-size:13.5px; min-width:720px}}
th{{
  font-family:var(--display); font-size:10.5px; font-weight:600; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted); text-align:left;
  padding:11px 14px; border-bottom:1px solid var(--line); white-space:nowrap;
}}
td{{padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:top}}
tr:last-child td{{border-bottom:0}}
td code{{font-size:12.5px; color:var(--ink)}}
td.notes{{font-family:var(--mono); font-size:11.5px; color:var(--muted); line-height:1.5}}

/* ---- ledger ---- */
.ledger{{display:grid; gap:0; margin-top:20px; border:1px solid var(--line);
  border-radius:var(--radius); overflow:hidden; background:var(--surface)}}
.ledger div{{display:grid; grid-template-columns:auto 1fr; gap:14px; padding:13px 18px;
  border-bottom:1px solid var(--line); align-items:baseline}}
.ledger div:last-child{{border-bottom:0}}
.ledger .tag{{align-self:start}}
.ledger p{{margin:0; font-size:14px}}
.ledger strong{{color:var(--ink); font-weight:600}}

footer{{margin-top:64px; padding-top:24px; border-top:1px solid var(--line);
  color:var(--muted); font-size:13px}}
footer code{{font-size:12.5px}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important; transition:none!important}}}}
</style>

<header class="mast"><div class="wrap">
  <p class="eyebrow">Certainti Tech Administration</p>
  <h1>Maintenance console</h1>
  <p class="lede">One place to run the platform's maintenance utilities across Dev, QA, Stage and
  Production — with a dry run by default, a second approver before production writes, and an
  append-only record of who ran what.</p>
</div></header>

<div class="wrap">

<div class="notice">
  <div class="bar"></div>
  <div>
    <p><strong>This is a preview, not a running deployment.</strong> The service has never been
    deployed — the sandbox that builds it is blocked from reaching Azure, so no VM exists yet.</p>
    <p>Everything below is real output from the code as it stands: the utility catalogue is
    generated from the registry, and the reports and audit records come from actually running the
    utilities. They ran against in-memory test doubles. <strong>No database has been contacted at
    any point.</strong></p>
  </div>
</div>

<section>
  <div class="shead"><h2>Environments</h2>
    <p>Credential readiness per database, read from the running configuration.</p></div>
  <div class="grid g4">{"".join(env_card(n) for n in ["dev","qa","stage","prod"])}</div>
</section>

<section>
  <div class="shead"><h2>Utilities</h2>
    <p>Generated from the registry — the API and the future UI read this same source.</p></div>
  <div class="grid g2">{"".join(util_card(u) for u in utils)}</div>
</section>

<section>
  <div class="shead"><h2>Shared data model</h2>
    <p>Produced by the analysis; every destructive utility refuses to write without it.</p></div>
  <div class="stats" style="margin-top:20px">
    <div class="stat"><div class="v">{model["summary"]["schemas"]}</div><div class="k">Tenant schemas</div></div>
    <div class="stat"><div class="v">{model["summary"]["tables"]}</div><div class="k">Tables</div></div>
    <div class="stat"><div class="v">{model["summary"]["references"]}</div><div class="k">Resolved references</div></div>
    <div class="stat"><div class="v">{model["summary"]["deviations"]}</div><div class="k">Naming deviations</div></div>
    <div class="stat"><div class="v" style="font-size:15px; padding-top:7px">{e(model["fingerprint"])}</div><div class="k">Model fingerprint</div></div>
  </div>
</section>

<section>
  <div class="shead"><h2>Run output</h2>
    <p>Verbatim, from running the utilities a few minutes ago.</p></div>
  <div class="term">
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected="true" aria-controls="p0" id="t0">Account purge — dry run</button>
      <button role="tab" aria-selected="false" aria-controls="p1" id="t1">Data-model analysis</button>
      <button role="tab" aria-selected="false" aria-controls="p2" id="t2">Purge console</button>
    </div>
    <pre role="tabpanel" id="p0" aria-labelledby="t0">{e(data["purge_report"])}</pre>
    <pre role="tabpanel" id="p1" aria-labelledby="t1" hidden>{e(data["analysis_report"])}</pre>
    <pre role="tabpanel" id="p2" aria-labelledby="t2" hidden>{e(data["purge_console"])}</pre>
  </div>
</section>

<section>
  <div class="shead"><h2>Audit trail</h2>
    <p>Written on every invocation, whether it succeeded, failed or was interrupted.</p></div>
  <div class="tablewrap"><table>
    <thead><tr><th>Utility</th><th>Env</th><th>Mode</th><th>Outcome</th><th>Started</th><th>Notes</th></tr></thead>
    <tbody>{"".join(audit_row(r) for r in audit)}</tbody>
  </table></div>
</section>

<section>
  <div class="shead"><h2>Where the build actually is</h2></div>
  <div class="ledger">
    <div><span class="tag ok">Built</span><p><strong>Four Python packages, 452 tests.</strong>
      Shared core, job orchestrator, account purge, data-model analysis. Lint clean.</p></div>
    <div><span class="tag ok">Built</span><p><strong>Terraform for a self-contained VM.</strong>
      Creates its own resource group, network, vault, identity and host. Changes nothing that
      already exists.</p></div>
    <div><span class="tag warn">Partial</span><p><strong>Web interface.</strong> A Next.js portal
      exists from Phase 0 and builds; the operator console that would replace it is Phase 3 and
      not started.</p></div>
    <div><span class="tag danger">Blocked</span><p><strong>Deployment.</strong> The gateway
      refuses <code>management.azure.com</code> and <code>registry.terraform.io</code> for this
      session's environment, so Terraform cannot download a provider, let alone apply.</p></div>
    <div><span class="tag danger">Blocked</span><p><strong>Anything touching a real database.</strong>
      The private endpoints do not resolve here and the bastion is unreachable. Every figure on
      this page came from test doubles.</p></div>
  </div>
</section>

<footer>
  <p>Rendered {e(model["generated_at"][:10])} from <code>certainti-ai/tech_administration</code>,
  branch <code>claude/certainti-tech-admin-y4c4ul</code>. Regenerate with
  <code>tools/preview/</code>.</p>
</footer>
</div>

<script>
const tabs = [...document.querySelectorAll('[role="tab"]')];
tabs.forEach((tab, i) => tab.addEventListener('click', () => {{
  tabs.forEach((t, j) => {{
    t.setAttribute('aria-selected', String(i === j));
    document.getElementById(t.getAttribute('aria-controls')).hidden = i !== j;
  }});
}}));
</script>
'''

open(OUT, "w").write(page)
print(f"wrote {OUT} ({len(page):,} bytes)")
