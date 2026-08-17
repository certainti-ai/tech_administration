#!/usr/bin/env python3
"""Generate an interactive ER-diagram + data-dictionary explorer (single self-
contained HTML) from data_dict.json (tables, row counts, FK edges across 3 DBs)."""
import json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SP = "/private/tmp/claude-501/-Users-prabhu-Documents-Code-Repo-trd365-maintenance/cec26643-e963-4c72-b4cf-8384b64de423/scratchpad"
DATA = json.load(open(f"{SP}/data_dict.json"))
DRIFT = json.load(open(f"{SP}/drift.json"))
OUT = HERE / "reports" / "er_explorer.html"
OUT.parent.mkdir(parents=True, exist_ok=True)

HTML = r"""<style>
:root{
  --bg:#f5f6f9; --surface:#ffffff; --surface2:#eef1f5; --surface3:#e5e9f0;
  --text:#171a21; --muted:#616b7d; --border:#e0e4ec; --shadow:0 1px 2px rgba(20,25,40,.06),0 8px 24px -12px rgba(20,25,40,.14);
  --accent:#3355e0;
  --org:#0d9488; --org-b:#0d948822; --main:#6366f1; --main-b:#6366f122; --ai:#d97706; --ai-b:#d9770622;
  --c-entity:#3355e0; --c-summary:#0891b2; --c-history:#7c3aed; --c-timeline:#0d9488;
  --c-staging:#b45309; --c-audit:#be123c; --c-junction:#4b5563;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0c0f16; --surface:#141922; --surface2:#1b212d; --surface3:#232c3a;
  --text:#e7ebf3; --muted:#8a95a9; --border:#28303e; --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 30px -14px rgba(0,0,0,.6);
  --accent:#5b7cff;
  --org:#2dd4bf; --org-b:#2dd4bf1f; --main:#8b93ff; --main-b:#8b93ff1f; --ai:#fbbf24; --ai-b:#fbbf241f;
  --c-entity:#7d97ff; --c-summary:#38bdf8; --c-history:#a78bfa; --c-timeline:#2dd4bf;
  --c-staging:#f59e0b; --c-audit:#fb7185; --c-junction:#94a3b8;
}}
:root[data-theme="dark"]{
  --bg:#0c0f16; --surface:#141922; --surface2:#1b212d; --surface3:#232c3a;
  --text:#e7ebf3; --muted:#8a95a9; --border:#28303e; --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 30px -14px rgba(0,0,0,.6);
  --accent:#5b7cff; --org:#2dd4bf; --org-b:#2dd4bf1f; --main:#8b93ff; --main-b:#8b93ff1f; --ai:#fbbf24; --ai-b:#fbbf241f;
  --c-entity:#7d97ff; --c-summary:#38bdf8; --c-history:#a78bfa; --c-timeline:#2dd4bf; --c-staging:#f59e0b; --c-audit:#fb7185; --c-junction:#94a3b8;
}
:root[data-theme="light"]{
  --bg:#f5f6f9; --surface:#ffffff; --surface2:#eef1f5; --surface3:#e5e9f0;
  --text:#171a21; --muted:#616b7d; --border:#e0e4ec; --accent:#3355e0;
  --org:#0d9488; --org-b:#0d948822; --main:#6366f1; --main-b:#6366f122; --ai:#d97706; --ai-b:#d9770622;
  --c-entity:#3355e0; --c-summary:#0891b2; --c-history:#7c3aed; --c-timeline:#0d9488; --c-staging:#b45309; --c-audit:#be123c; --c-junction:#4b5563;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
.app{display:flex;flex-direction:column;height:100vh;overflow:hidden}
header{display:flex;align-items:center;gap:16px;padding:12px 20px;background:var(--surface);border-bottom:1px solid var(--border);flex-wrap:wrap}
.brand{display:flex;flex-direction:column;gap:1px}
.brand h1{margin:0;font-size:15px;font-weight:650;letter-spacing:-.01em}
.brand span{font-size:11.5px;color:var(--muted)}
.stats{display:flex;gap:6px;margin-left:4px;flex-wrap:wrap}
.stat{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:5px 10px;font-size:11.5px;color:var(--muted);white-space:nowrap}
.stat b{color:var(--text);font-size:13px;font-variant-numeric:tabular-nums}
.grow{flex:1}
.search{position:relative}
.search input{width:230px;max-width:44vw;padding:7px 11px 7px 30px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:13px}
.search input:focus{outline:2px solid var(--accent);outline-offset:-1px;border-color:transparent}
.search svg{position:absolute;left:9px;top:8px;width:14px;height:14px;color:var(--muted)}
.tabs{display:flex;background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:2px}
.tabs button{border:0;background:transparent;color:var(--muted);padding:6px 13px;border-radius:7px;font-family:var(--sans);font-size:12.5px;font-weight:550;cursor:pointer}
.tabs button.on{background:var(--surface);color:var(--text);box-shadow:var(--shadow)}
.theme{border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:8px;width:32px;height:32px;cursor:pointer;font-size:14px}
main{flex:1;display:flex;min-height:0}
/* explorer */
.sidebar{width:340px;min-width:280px;border-right:1px solid var(--border);background:var(--surface);overflow-y:auto;padding:8px}
.dbgroup{margin-bottom:6px}
.dbhead{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer;border-radius:9px;user-select:none}
.dbhead:hover{background:var(--surface2)}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.dbhead .nm{font-weight:650;font-size:12.5px;letter-spacing:.02em;text-transform:uppercase}
.dbhead .schema{font-family:var(--mono);font-size:11px;color:var(--muted)}
.dbhead .cnt{margin-left:auto;font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
.caret{transition:transform .15s;color:var(--muted);font-size:10px}
.collapsed .caret{transform:rotate(-90deg)}
.domgroup{margin:2px 0 2px 12px}
.domhead{display:flex;align-items:center;gap:7px;padding:5px 9px;cursor:pointer;border-radius:7px;font-size:11.5px;color:var(--muted);user-select:none}
.domhead:hover{background:var(--surface2)}
.domhead .dnm{font-weight:600;text-transform:capitalize;color:var(--text)}
.domhead .cnt{margin-left:auto;font-variant-numeric:tabular-nums}
.tlist{margin-left:14px;border-left:1px solid var(--border);padding-left:4px}
.trow{display:flex;align-items:center;gap:7px;padding:5px 8px;border-radius:7px;cursor:pointer;font-family:var(--mono);font-size:12px}
.trow:hover{background:var(--surface2)}
.trow.sel{background:var(--accent);color:#fff}
.trow.sel .rows,.trow.sel .cat{color:#fff;opacity:.9}
.trow .tn{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trow .rows{font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.cat{width:7px;height:7px;border-radius:2px;flex:none}
.hidden{display:none!important}
/* detail */
.detail{flex:1;overflow-y:auto;padding:22px 26px}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--muted);gap:10px;text-align:center}
.dhead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:4px}
.dhead h2{margin:0;font-family:var(--mono);font-size:22px;font-weight:600;letter-spacing:-.01em}
.pill{font-size:11px;padding:3px 9px;border-radius:20px;font-weight:600;border:1px solid transparent}
.metrics{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 22px}
.metric{background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:12px 16px;min-width:96px;box-shadow:var(--shadow)}
.metric .v{font-size:21px;font-weight:650;font-variant-numeric:tabular-nums}
.metric .l{font-size:11px;color:var(--muted);margin-top:2px}
.sec{margin:22px 0}
.sec h3{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 10px}
.egowrap{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:6px;box-shadow:var(--shadow);overflow-x:auto}
svg.ego{display:block;min-width:100%}
.node rect{rx:8;stroke-width:1.5}
.node text{font-family:var(--mono);font-size:11px;fill:var(--text)}
.node .sub{font-size:9px;fill:var(--muted)}
.edge{stroke:var(--border);stroke-width:1.4;fill:none}
.edge-lbl{font-family:var(--mono);font-size:8.5px;fill:var(--muted)}
.rels{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.rels{grid-template-columns:1fr}}
.relcard{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:4px;box-shadow:var(--shadow)}
.relcard .rh{padding:9px 12px;font-size:11px;color:var(--muted);font-weight:600}
.rel{display:flex;align-items:center;gap:8px;padding:7px 12px;border-radius:8px;cursor:pointer;font-family:var(--mono);font-size:12px}
.rel:hover{background:var(--surface2)}
.rel .card{margin-left:auto;font-size:10px;color:var(--muted);background:var(--surface2);padding:2px 7px;border-radius:20px}
.rel .via{color:var(--muted);font-size:10.5px}
.muted{color:var(--muted)}
.cols{display:flex;flex-wrap:wrap;gap:5px}
.colchip{font-family:var(--mono);font-size:11px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:3px 8px}
.colchip.pk{border-color:var(--accent);color:var(--accent)}
.colchip.fk{border-color:var(--c-history)}
/* dictionary */
.dict{flex:1;overflow:auto;padding:18px 22px}
table.dd{width:100%;border-collapse:collapse;font-size:12.5px}
table.dd th{position:sticky;top:0;background:var(--surface);text-align:left;padding:9px 12px;border-bottom:2px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);cursor:pointer;white-space:nowrap;z-index:1}
table.dd th:hover{color:var(--text)}
table.dd td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
table.dd tr:hover td{background:var(--surface2)}
td.tn{font-family:var(--mono);cursor:pointer}
td.tn:hover{color:var(--accent)}
td.num{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono)}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--border);white-space:nowrap}
/* columns */
.collist{display:flex;flex-direction:column;gap:2px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:6px;box-shadow:var(--shadow)}
.crow{display:flex;align-items:center;gap:12px;padding:7px 12px;border-radius:8px}
.crow:hover{background:var(--surface2)}
.crow .cn{font-family:var(--mono);font-size:12.5px;min-width:210px;font-weight:500}
.crow .cty{font-family:var(--mono);font-size:11.5px;color:var(--c-summary);min-width:90px}
.cbs{display:flex;gap:5px;flex-wrap:wrap;margin-left:auto}
.cb{font-size:10px;padding:2px 7px;border-radius:5px;font-weight:600;border:1px solid var(--border);color:var(--muted);white-space:nowrap}
.cb.pk{color:var(--accent);border-color:var(--accent)}
.cb.uq{color:var(--c-summary);border-color:var(--c-summary)}
.cb.fk{color:var(--c-history);border-color:var(--c-history);font-family:var(--mono)}
.cb.nn{color:var(--muted)} .cb.df{color:var(--muted)}
.cb.dr,.cb.pt,.cb.ty{color:var(--c-staging);border-color:var(--c-staging);background:var(--c-staging)14}
.cb.ty{color:var(--c-audit);border-color:var(--c-audit);background:var(--c-audit)14}
/* drift */
.driftcard{background:var(--surface);border:1px solid var(--border);border-radius:12px;margin-bottom:8px;box-shadow:var(--shadow);overflow:hidden}
.dch{display:flex;align-items:center;gap:10px;padding:12px 14px;cursor:pointer;user-select:none}
.dch:hover{background:var(--surface2)}
.dch .cn{font-family:var(--mono);font-weight:600}
.driftcard.collapsed .dcb{display:none}
.driftcard.collapsed .caret{transform:rotate(-90deg)}
.dcb{padding:4px 14px 12px;border-top:1px solid var(--border)}
.dcol{display:flex;align-items:center;gap:10px;padding:6px 4px;flex-wrap:wrap}
.dcol .cn{font-family:var(--mono);font-size:12px;min-width:230px}
.dcol .via{font-family:var(--mono);font-size:11px;color:var(--muted)}
.legend{display:flex;gap:14px;flex-wrap:wrap;padding:10px 22px;border-top:1px solid var(--border);background:var(--surface);font-size:11px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.footer{padding:8px 22px;font-size:11px;color:var(--muted);background:var(--surface);border-top:1px solid var(--border)}
</style>

<div class="app">
  <header>
    <div class="brand"><h1>TRD365 · Data-Model Explorer</h1><span>Interactive ER diagram &amp; data dictionary — Org · Main · TRD365AI</span></div>
    <div class="stats" id="stats"></div>
    <div class="grow"></div>
    <div class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg><input id="q" placeholder="Search tables…" autocomplete="off"></div>
    <div class="tabs"><button id="tabExp" class="on">Explorer</button><button id="tabDict">Data Dictionary</button><button id="tabDrift">Schema Drift</button></div>
    <button class="theme" id="theme" title="Toggle theme">◐</button>
  </header>
  <main id="viewExp">
    <aside class="sidebar" id="tree"></aside>
    <section class="detail" id="detail"><div class="empty"><div style="font-size:40px">◧</div><div>Select a table to explore its columns &amp; relationships</div></div></section>
  </main>
  <div class="dict hidden" id="viewDict"></div>
  <div class="dict hidden" id="viewDrift"></div>
  <div class="legend" id="legend"></div>
  <div class="footer" id="footer"></div>
</div>

<script>
const DATA = __DATA__;
const DRIFT = __DRIFT__;
const DB = {org:{label:"Org",color:"var(--org)",bd:"var(--org-b)"},main:{label:"Main",color:"var(--main)",bd:"var(--main-b)"},ai:{label:"AI",color:"var(--ai)",bd:"var(--ai-b)"}};
const CATCOL = {entity:"--c-entity",summary:"--c-summary",history:"--c-history",timeline:"--c-timeline",staging:"--c-staging",audit:"--c-audit",junction:"--c-junction"};
function category(t){
  if(/^history_staging|_staging$/.test(t))return"staging";
  if(/_timeline(_old)?$/.test(t))return"timeline";
  if(/_history$/.test(t))return"history";
  if(/_audit$/.test(t))return"audit";
  if(/_summary(_bk)?$/.test(t))return"summary";
  if(/^case_project|_by_region$|_mapping$|^project_resource$/.test(t))return"junction";
  return"entity";
}
function domain(t){
  if(/^(case|rd_|signoff|dossier|checklist)/.test(t))return"case";
  if(/^(interaction|otp|four_part|autosend)/.test(t))return"interaction";
  if(/^(resource|resources)/.test(t))return"resource";
  if(/^chat/.test(t))return"chat";
  if(/^project/.test(t))return"project";
  if(/^(account|user_group|subscription|control_center|rule_engine|send_email|master_|ai_|kafka)/.test(t))return"account";
  return"other";
}
// ── build index ───────────────────────────────────────────────────────────
const IDX={}; // key `${db}.${table}` -> {db,name,rows,ncols,pk,fks,cat,dom,childrenOf:[]}
const ALL=[];
for(const db of ["org","main","ai"]){
  const d=DATA[db]; for(const [name,t] of Object.entries(d.tables)){
    const o={db,name,rows:t.rows,ncols:t.ncols,pk:t.pk,fks:t.fks||[],columns:t.columns||[],cat:category(name),dom:domain(name),children:[]};
    IDX[db+"."+name]=o; ALL.push(o);
  }
}
// reverse edges (who references me, within same db)
for(const o of ALL){ for(const fk of o.fks){ const p=IDX[o.db+"."+fk.parent]; if(p) p.children.push({child:o.name,col:fk.col}); } }
const nf=n=>n>=1e6?(n/1e6).toFixed(n>=1e7?0:1)+"M":n>=1e3?(n/1e3).toFixed(n>=1e4?0:1)+"k":""+n;
const totalRows=ALL.reduce((s,o)=>s+o.rows,0), totalFk=ALL.reduce((s,o)=>s+o.fks.length,0);

// ── stats ─────────────────────────────────────────────────────────────────
document.getElementById("stats").innerHTML=
  `<div class="stat"><b>${ALL.length}</b> tables</div>`+
  `<div class="stat"><b>${totalFk}</b> relationships</div>`+
  `<div class="stat"><b>~${nf(totalRows)}</b> rows</div>`+
  ["org","main","ai"].map(db=>`<div class="stat" style="border-color:${DB[db].color}"><span class="dot" style="background:${DB[db].color};display:inline-block;margin-right:5px"></span><b>${DATA[db].schema==='trd365'?'trd365':DATA[db].schema}</b> ${Object.keys(DATA[db].tables).length}</div>`).join("");

// ── legend ──────────────────────────────────────────────────────────────────
document.getElementById("legend").innerHTML="<b style='color:var(--text)'>Category:</b> "+Object.keys(CATCOL).map(c=>`<span><i class="cat" style="background:var(${CATCOL[c]})"></i>${c}</span>`).join("")+
  "&nbsp;&nbsp;<b style='color:var(--text)'>DB:</b> "+["org","main","ai"].map(db=>`<span><i class="dot" style="background:${DB[db].color}"></i>${DB[db].label}</span>`).join("");
document.getElementById("footer").textContent=`Org row counts from a representative tenant schema (${DATA.org.schema}); Main/AI are the live shared schemas. Row counts are planner estimates (pg_class.reltuples). Cardinality shown as N:1 (child→parent) / 1:N (parent→children).`;

// ── sidebar tree ────────────────────────────────────────────────────────────
let SEL=null, FILTER="";
function domsFor(db){const m={};for(const o of ALL){if(o.db!==db)continue;(m[o.dom]=m[o.dom]||[]).push(o);}for(const k in m)m[k].sort((a,b)=>b.rows-a.rows||a.name.localeCompare(b.name));return m;}
const domOrder=["account","project","resource","case","interaction","chat","other"];
function renderTree(){
  const el=document.getElementById("tree"); el.innerHTML="";
  for(const db of ["org","main","ai"]){
    const doms=domsFor(db); const g=document.createElement("div"); g.className="dbgroup";
    const tot=Object.values(doms).reduce((s,a)=>s+a.length,0);
    const head=document.createElement("div"); head.className="dbhead";
    head.innerHTML=`<span class="caret">▼</span><span class="dot" style="background:${DB[db].color}"></span><span class="nm" style="color:${DB[db].color}">${DB[db].label}</span><span class="schema">${DATA[db].schema}</span><span class="cnt">${tot}</span>`;
    const body=document.createElement("div");
    head.onclick=()=>{g.classList.toggle("collapsed");body.classList.toggle("hidden");};
    g.append(head,body);
    for(const dom of domOrder){ const list=doms[dom]; if(!list)continue;
      const dg=document.createElement("div"); dg.className="domgroup";
      const dh=document.createElement("div"); dh.className="domhead";
      dh.innerHTML=`<span class="caret">▼</span><span class="dnm">${dom}</span><span class="cnt">${list.length}</span>`;
      const tl=document.createElement("div"); tl.className="tlist";
      dh.onclick=()=>{dg.classList.toggle("collapsed");tl.classList.toggle("hidden");};
      for(const o of list){
        const r=document.createElement("div"); r.className="trow"; r.dataset.key=o.db+"."+o.name;
        r.innerHTML=`<span class="cat" style="background:var(${CATCOL[o.cat]})" title="${o.cat}"></span><span class="tn">${o.name}</span><span class="rows">${nf(o.rows)}</span>`;
        r.onclick=()=>select(o.db+"."+o.name);
        tl.append(r);
      }
      dg.append(dh,tl); body.append(dg);
    }
    el.append(g);
  }
  applyFilter();
}
function applyFilter(){
  const f=FILTER.toLowerCase();
  document.querySelectorAll(".dbgroup").forEach(g=>{
    let dbVis=0;
    g.querySelectorAll(".domgroup").forEach(dg=>{
      let vis=0;
      dg.querySelectorAll(".trow").forEach(r=>{const m=!f||r.dataset.key.split(".")[1].includes(f);r.classList.toggle("hidden",!m);if(m)vis++;});
      dg.classList.toggle("hidden",vis===0); dbVis+=vis;
      if(f&&vis){dg.classList.remove("collapsed");dg.querySelector(".tlist").classList.remove("hidden");}
    });
    g.classList.toggle("hidden",dbVis===0);
    if(f&&dbVis){g.classList.remove("collapsed");g.querySelector(".dbhead+div").classList.remove("hidden");}
  });
}
// ── detail + ego graph ──────────────────────────────────────────────────────
function pill(txt,color,bg){return `<span class="pill" style="color:${color};background:${bg};border-color:${color}44">${txt}</span>`;}
function select(key){
  SEL=key; const o=IDX[key]; if(!o)return;
  document.querySelectorAll(".trow").forEach(r=>r.classList.toggle("sel",r.dataset.key===key));
  const parents=o.fks.filter(f=>IDX[o.db+"."+f.parent]);
  const children=o.children;
  const catc=`var(${CATCOL[o.cat]})`;
  let h=`<div class="dhead"><h2>${o.name}</h2>`+
    pill(DB[o.db].label,DB[o.db].color,DB[o.db].bd)+
    pill(o.dom,"var(--muted)","var(--surface2)")+
    pill(o.cat,catc,"transparent")+
    (o.pk?pill("PK","var(--accent)","transparent"):pill("no PK","var(--c-audit)","transparent"))+`</div>`;
  h+=`<div class="metrics">
    <div class="metric"><div class="v">${o.rows.toLocaleString()}</div><div class="l">rows (est.)</div></div>
    <div class="metric"><div class="v">${o.ncols}</div><div class="l">columns</div></div>
    <div class="metric"><div class="v">${parents.length}</div><div class="l">references →</div></div>
    <div class="metric"><div class="v">${children.length}</div><div class="l">← referenced by</div></div></div>`;
  h+=`<div class="sec"><h3>Relationship graph</h3><div class="egowrap">${ego(o,parents,children)}</div></div>`;
  h+=`<div class="sec"><h3>Relationships &amp; cardinality</h3><div class="rels">`;
  h+=`<div class="relcard"><div class="rh">References (this → parent) · N:1</div>`+
     (parents.length?parents.map(f=>relRow(o.db,f.parent,f.col,"N:1")).join(""):`<div class="rel muted">— none —</div>`)+`</div>`;
  h+=`<div class="relcard"><div class="rh">Referenced by (child → this) · 1:N</div>`+
     (children.length?children.slice(0,60).map(c=>relRow(o.db,c.child,c.col,"1:N")).join("")+(children.length>60?`<div class="rel muted">+${children.length-60} more…</div>`:""):`<div class="rel muted">— none —</div>`)+`</div>`;
  h+=`</div></div>`;
  const drT = o.db==="org"?(DRIFT.drift[o.name]||null):null;
  h+=`<div class="sec"><h3>Columns · ${o.columns.length}`+
     (drT?` <span class="cb dr" style="text-transform:none">⚠ ${drT.n_partial+drT.n_type} inconsistent across tenants</span>`:"")+
     `</h3><div class="collist">`+ o.columns.map(c=>colRow(c,drT)).join("") +`</div></div>`;
  const d=document.getElementById("detail"); d.innerHTML=h; d.scrollTop=0;
  d.querySelectorAll("[data-goto]").forEach(e=>e.onclick=()=>select(e.dataset.goto));
}
function colRow(c,drT){
  const dr = drT && drT.cols[c.n];
  let b="";
  if(c.pk)b+=`<span class="cb pk">PK</span>`;
  if(c.uq)b+=`<span class="cb uq">UNIQUE</span>`;
  if(c.fk)b+=`<span class="cb fk">FK→${c.fk}</span>`;
  if(!c.null)b+=`<span class="cb nn">NOT NULL</span>`;
  if(c.def)b+=`<span class="cb df">default</span>`;
  if(dr){const parts=[];if(dr.missing_in)parts.push(`missing in ${dr.missing_in.length}: ${dr.missing_in.join(", ")}`);if(dr.types)parts.push("types: "+Object.entries(dr.types).map(([t,n])=>`${t}×${n}`).join(", "));b+=`<span class="cb dr" title="${parts.join(' | ')}">⚠ drift</span>`;}
  return `<div class="crow"><span class="cn">${c.n}</span><span class="cty">${c.ty}</span><span class="cbs">${b}</span></div>`;
}
function relRow(db,name,col,card){
  const t=IDX[db+"."+name]; const c=t?`var(${CATCOL[t.cat]})`:"var(--muted)";
  return `<div class="rel" ${t?`data-goto="${db}.${name}"`:""}><span class="cat" style="background:${c}"></span><span>${name}</span><span class="via">.${col}</span>${t?`<span class="card">${card} · ${nf(t.rows)}</span>`:`<span class="card">${card}</span>`}</div>`;
}
function ego(o,parents,children){
  const W=Math.max(720,Math.max(parents.length,Math.min(children.length,8))*150+60);
  const colW=150, cx=W/2, topY=54, midY=170, botY=286, H=childRows(children)>1?360:330;
  const cardc=DB[o.db].color;
  function box(x,y,t,sub,fill,stroke,goto){
    const w=134,h=40,rx=x-w/2;
    return `<g class="node" ${goto?`data-goto="${goto}" style="cursor:pointer"`:""} transform="translate(0,0)">
      <rect x="${rx}" y="${y}" width="${w}" height="${h}" rx="8" fill="${fill}" stroke="${stroke}"/>
      <text x="${x}" y="${y+17}" text-anchor="middle">${clip(t)}</text>
      <text x="${x}" y="${y+31}" text-anchor="middle" class="sub">${sub}</text></g>`;
  }
  function clip(s){return s.length>17?s.slice(0,16)+"…":s;}
  let svg=`<svg class="ego" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;
  // parents (above)
  const pn=parents.length||1;
  parents.forEach((f,i)=>{const x=W/2+(i-(pn-1)/2)*Math.min(colW,(W-80)/pn);const t=IDX[o.db+"."+f.parent];
    svg+=`<path class="edge" d="M ${cx} ${midY} C ${cx} ${midY-40}, ${x} ${topY+70}, ${x} ${topY+40}"/>`;
    svg+=`<text class="edge-lbl" x="${(cx+x)/2}" y="${(midY+topY+40)/2}">N:1</text>`;
    svg+=box(x,topY,f.parent,t?nf(t.rows)+" rows":"ext",`var(--surface2)`,`var(--border)`,t?o.db+"."+f.parent:null);});
  // center
  svg+=box(cx,midY,o.name,nf(o.rows)+" rows",DB[o.db].bd,cardc,null);
  // children (below, up to 8 across, may wrap 2 rows)
  const shown=children.slice(0,16), per=Math.min(8,Math.max(shown.length,1));
  shown.forEach((c,i)=>{const row=Math.floor(i/per),colN=i%per,inRow=Math.min(per,shown.length-row*per);
    const x=W/2+(colN-(inRow-1)/2)*Math.min(colW,(W-80)/per), y=botY+row*54;
    const t=IDX[o.db+"."+c.child];
    svg+=`<path class="edge" d="M ${cx} ${midY+40} C ${cx} ${midY+70}, ${x} ${y-30}, ${x} ${y}"/>`;
    if(row===0)svg+=`<text class="edge-lbl" x="${(cx+x)/2}" y="${(midY+40+y)/2}">1:N</text>`;
    svg+=box(x,y,c.child,t?nf(t.rows):"",`var(--surface2)`,`var(--border)`,t?o.db+"."+c.child:null);});
  if(children.length>16)svg+=`<text class="edge-lbl" x="${cx}" y="${botY+2*54+16}" text-anchor="middle">+${children.length-16} more referencing tables</text>`;
  svg+=`</svg>`;
  return svg;
}
function childRows(children){return Math.ceil(Math.min(children.length,16)/8);}
// ── data dictionary ─────────────────────────────────────────────────────────
let sortKey="rows",sortDir=-1;
function renderDict(){
  const cols=[["name","Table"],["db","DB"],["dom","Domain"],["cat","Category"],["rows","Rows (est.)"],["ncols","Cols"],["pk","PK"],["nfk","Refs →"],["nchild","← Ref by"]];
  let rows=ALL.map(o=>({...o,nfk:o.fks.length,nchild:o.children.length}));
  const f=FILTER.toLowerCase(); if(f)rows=rows.filter(o=>o.name.includes(f));
  rows.sort((a,b)=>{let x=a[sortKey],y=b[sortKey];if(typeof x==="string")return sortDir*x.localeCompare(y);return sortDir*((x||0)-(y||0));});
  let h=`<table class="dd"><thead><tr>`+cols.map(c=>`<th data-k="${c[0]}">${c[1]}${sortKey===c[0]?(sortDir<0?" ▾":" ▴"):""}</th>`).join("")+`</tr></thead><tbody>`;
  for(const o of rows){
    h+=`<tr><td class="tn" data-goto="${o.db}.${o.name}">${o.name}</td>`+
      `<td><span class="badge" style="border-color:${DB[o.db].color};color:${DB[o.db].color}"><i class="dot" style="background:${DB[o.db].color}"></i>${DB[o.db].label}</span></td>`+
      `<td class="muted">${o.dom}</td>`+
      `<td><span class="badge"><i class="cat" style="background:var(${CATCOL[o.cat]})"></i>${o.cat}</span></td>`+
      `<td class="num">${o.rows.toLocaleString()}</td><td class="num">${o.ncols}</td>`+
      `<td>${o.pk?"✓":'<span class="muted">—</span>'}</td>`+
      `<td class="num">${o.nfk||'<span class="muted">0</span>'}</td><td class="num">${o.nchild||'<span class="muted">0</span>'}</td></tr>`;
  }
  h+=`</tbody></table>`;
  const el=document.getElementById("viewDict"); el.innerHTML=h;
  el.querySelectorAll("th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=(k==="name"||k==="db"||k==="dom"||k==="cat")?1:-1;}renderDict();});
  el.querySelectorAll("td.tn").forEach(td=>td.onclick=()=>{select(td.dataset.goto);showTab("exp");});
}
// ── tabs / theme / search ────────────────────────────────────────────────────
function showTab(t){
  document.getElementById("tabExp").classList.toggle("on",t==="exp");
  document.getElementById("tabDict").classList.toggle("on",t==="dict");
  document.getElementById("tabDrift").classList.toggle("on",t==="drift");
  document.getElementById("viewExp").classList.toggle("hidden",t!=="exp");
  document.getElementById("viewDict").classList.toggle("hidden",t!=="dict");
  document.getElementById("viewDrift").classList.toggle("hidden",t!=="drift");
  if(t==="dict")renderDict();
  if(t==="drift")renderDrift();
}
document.getElementById("tabExp").onclick=()=>showTab("exp");
document.getElementById("tabDict").onclick=()=>showTab("dict");
document.getElementById("tabDrift").onclick=()=>showTab("drift");
function renderDrift(){
  const f=FILTER.toLowerCase();
  let items=Object.entries(DRIFT.drift).map(([t,i])=>({t,...i})).filter(x=>!f||x.t.includes(f));
  items.sort((a,b)=>(b.n_partial+b.n_type)-(a.n_partial+a.n_type)||b.n_schemas-a.n_schemas);
  let h=`<div style="max-width:1100px">
    <div class="metrics" style="margin:4px 0 18px">
      <div class="metric"><div class="v">${DRIFT.n_tenant_schemas}</div><div class="l">tenant schemas</div></div>
      <div class="metric"><div class="v">${DRIFT.tables_compared}</div><div class="l">tables compared</div></div>
      <div class="metric"><div class="v" style="color:var(--org)">${DRIFT.tables_consistent}</div><div class="l">fully consistent</div></div>
      <div class="metric"><div class="v" style="color:var(--c-staging)">${DRIFT.tables_with_drift}</div><div class="l">with drift</div></div>
    </div>
    <p class="muted" style="margin:0 0 14px">Columns compared across all <b>${DRIFT.n_tenant_schemas}</b> Org tenant schemas (<span style="font-family:var(--mono);font-size:11px">${DRIFT.schemas.join(", ")}</span>). A table drifts when a column is missing in some schemas (<b>partial</b>) or has different data types across schemas (<b>type</b>).</p>`;
  for(const x of items){
    h+=`<div class="driftcard"><div class="dch" data-tgl>
      <span class="caret">▼</span><span class="cn" style="font-size:14px">${x.t}</span>
      <span class="muted" style="font-size:11.5px">in ${x.n_schemas}/${DRIFT.n_tenant_schemas} schemas · ${x.ncols_union} columns (union)</span>
      <span style="margin-left:auto"></span>
      ${x.n_partial?`<span class="cb pt">${x.n_partial} partial</span>`:""}
      ${x.n_type?`<span class="cb ty">${x.n_type} type</span>`:""}</div>
      <div class="dcb">`;
    for(const [col,r] of Object.entries(x.cols)){
      h+=`<div class="dcol"><span class="cn">${col}</span>`;
      if(r.missing_in)h+=`<span class="cb pt">present ${r.present}/${x.n_schemas}</span><span class="via">missing in: ${r.missing_in.join(", ")}</span>`;
      if(r.types)h+=`<span class="cb ty">types</span><span class="via">${Object.entries(r.types).map(([t,n])=>`<b>${t}</b>×${n}`).join(" · ")}</span>`;
      h+=`</div>`;
    }
    h+=`</div></div>`;
  }
  const el=document.getElementById("viewDrift"); el.innerHTML=h;
  el.querySelectorAll("[data-tgl]").forEach(e=>e.onclick=()=>e.parentElement.classList.toggle("collapsed"));
}
document.getElementById("q").addEventListener("input",e=>{FILTER=e.target.value.trim();applyFilter();if(!document.getElementById("viewDict").classList.contains("hidden"))renderDict();});
document.getElementById("theme").onclick=()=>{const r=document.documentElement;const cur=r.getAttribute("data-theme")|| (matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");r.setAttribute("data-theme",cur==="dark"?"light":"dark");};
renderTree();
</script>
"""

OUT.write_text(HTML.replace("__DATA__", json.dumps(DATA, separators=(",", ":")))
                   .replace("__DRIFT__", json.dumps(DRIFT, separators=(",", ":"))))
print("wrote", OUT, OUT.stat().st_size, "bytes")
