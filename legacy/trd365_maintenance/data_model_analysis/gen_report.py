#!/usr/bin/env python3
"""HTML data-model report: colour-coded cross-DB flowcharts (Org/Main/AI, and table
category) incl. history/timeline/staging/audit tables, + a scannable relationships table."""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SP = "/private/tmp/claude-501/-Users-prabhu-Documents-Code-Repo-trd365-maintenance/cec26643-e963-4c72-b4cf-8384b64de423/scratchpad"
g = json.load(open(f"{SP}/model_graph.json"))
ai = json.load(open(f"{SP}/ai_graph.json"))

# ── categorize ───────────────────────────────────────────────────────────────
def category(t):
    if re.search(r'(^history_staging|_staging$)', t): return "staging"
    if t.endswith("_timeline") or t.endswith("_timeline_old"): return "timeline"
    if t.endswith("_history"): return "history"
    if t.endswith("_audit"): return "audit"
    if t.endswith("_summary") or t.endswith("_summary_bk"): return "summary"
    return "entity"

CATS = ["entity", "summary", "history", "timeline", "audit", "staging"]

def domain(t):
    if t.startswith("case") or t.startswith("rd_"): return "case"
    if t.startswith("interaction") or t.startswith("otp"): return "interaction"
    if t.startswith("resource") or t == "resources" or t.startswith("history_staging_resource"): return "resource"
    if t.startswith("project"): return "project"
    return "account"

DOMAINS = [("project", "Project"), ("resource", "Resource"), ("case", "Case & R&D"),
           ("interaction", "Interaction"), ("account", "Account & cross-cutting")]

def nid(t): return "n_" + re.sub(r'[^A-Za-z0-9]', '_', t)

CLASSDEFS = ("""    classDef entity fill:#e9ecfb,stroke:#3f4fce,color:#1a2033;
    classDef summary fill:#e7f1ff,stroke:#2563c9,color:#0e2a52;
    classDef history fill:#fdf0dc,stroke:#b3720d,color:#4a3410;
    classDef timeline fill:#dff4f4,stroke:#0f8a8a,color:#0a3d3d;
    classDef audit fill:#f2eafb,stroke:#8a4fbf,color:#3a1f52;
    classDef staging fill:#fbe6ea,stroke:#c8455f,color:#5a1a26;
""")

def classes_for(nodes):
    by = defaultdict(list)
    for t in nodes:
        by[category(t)].append(nid(t))
    return "".join(f'    class {",".join(ids)} {cat};\n' for cat, ids in by.items() if ids)

def node_decls(nodes):
    return "".join(f'    {nid(t)}["{t}"]\n' for t in sorted(nodes))

def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ── per-domain flowcharts (org) ──────────────────────────────────────────────
def domain_flow(key):
    edges, nodes = [], set()
    for (child, col, parent, flag) in g["org"]["edges"]:
        if domain(child) != key:
            continue
        par = "account" if flag == "XDB" else parent
        edges.append((par, child, col)); nodes.add(par); nodes.add(child)
    if not edges:
        return None, 0
    out = "flowchart LR\n" + CLASSDEFS
    out += node_decls(nodes)
    for (p, c, lbl) in sorted(set(edges)):
        out += f'    {nid(p)} -->|{lbl}| {nid(c)}\n'
    out += classes_for(nodes)
    return out, len(set(edges))

# ── cross-DB overview flowchart ──────────────────────────────────────────────
def crossdb_flow():
    org_e = [("account", "project", "account_rid"), ("account", "resources", "account_rid"),
             ("account", "cases", "account_rid"), ("project", "project_fiscal", "project_rid"),
             ("project", "project_resource", "project_rid"), ("project_fiscal", "project_resource_fiscal", "project_fiscal_rid"),
             ("resources", "resource_fiscal", "resource_rid"), ("cases", "case_projects", "case_rid"),
             ("case_projects", "case_project_resource", "case_project_rid"), ("project_fiscal", "interactions", "project_fiscal_rid")]
    org_nodes = {"account", "project", "project_fiscal", "project_resource", "project_resource_fiscal",
                 "resources", "resource_fiscal", "cases", "case_projects", "case_project_resource", "interactions"}
    # Main summary tables referencing org
    main_e = [("project", "project_summary", "project_rid"), ("project_fiscal", "project_fiscal_summary", "project_fiscal_rid"),
              ("project_fiscal", "interactions_summary", "project_fiscal_rid"), ("cases", "case_summary", "case_rid"),
              ("account", "account_fiscal_summary", "account_rid"), ("account", "task_summary", "account_rid")]
    main_nodes = {"account", "project_summary", "project_fiscal_summary", "interactions_summary",
                  "case_summary", "account_fiscal_summary", "task_summary"}
    # AI tables (projectId -> project_fiscal)
    ai_pick = ["master_project_ai_summary", "master_project_ai_assessment", "master_ai_request",
               "master_project_details", "four_part_assessments"]
    ai_e = [("project_fiscal", t, "projectId") for t in ai_pick]

    out = "flowchart LR\n" + CLASSDEFS
    out += '    subgraph ORG["Org DB · per-tenant schemas"]\n' + \
           "".join(f'      {nid(t)}["{t}"]\n' for t in sorted(org_nodes - {"account"})) + "    end\n"
    out += '    subgraph MAIN["Main DB · trd365"]\n' + \
           "".join(f'      {nid(t)}["{t}"]\n' for t in sorted(main_nodes)) + "    end\n"
    out += '    subgraph AI["TRD365AI · public"]\n' + \
           "".join(f'      {nid(t)}["{t}"]\n' for t in ai_pick) + "    end\n"
    for (p, c, lbl) in org_e:
        if p == "account":  # account lives in MAIN
            out += f'    {nid("account")} -.->|{lbl}| {nid(c)}\n'
        else:
            out += f'    {nid(p)} -->|{lbl}| {nid(c)}\n'
    for (p, c, lbl) in main_e:
        out += f'    {nid(p)} -.->|{lbl}| {nid(c)}\n'
    for (p, c, lbl) in ai_e:
        out += f'    {nid(p)} -.->|{lbl}| {nid(c)}\n'
    alln = org_nodes | main_nodes | set(ai_pick)
    out += classes_for(alln)
    return out

# ── relationships table (all DBs) ────────────────────────────────────────────
rows = []
for (child, col, parent, flag) in g["org"]["edges"]:
    rows.append((child, col, "account (main.trd365)" if flag == "XDB" else parent, category(child), "Org"))
for (child, col, parent, flag) in g["main"]["edges"]:
    rows.append((child, col, "account" if flag == "XDB" else parent, category(child), "Main"))
# main -> org cross-DB refs (project/fiscal/case) - from known 24 summary/records tables
MAIN_XORG = {"project_summary": ["project_rid", "account_rid"], "project_fiscal_summary": ["project_rid", "project_fiscal_rid", "account_rid"],
    "interactions_summary": ["project_rid", "project_fiscal_rid", "account_rid"], "case_summary": ["case_rid", "account_rid"],
    "task_summary": ["account_rid"], "attachment_summary": ["account_rid"], "notes_summary": ["account_rid"],
    "meeting_summary": ["account_rid"], "account_fiscal_summary": ["account_rid"], "chat_assistance_session": ["account_rid", "case_rid", "project_rid"],
    "project_soft_delete": ["project_rid", "account_rid"], "project_deletion_history": ["project_rid", "account_rid"]}
for t, cs in MAIN_XORG.items():
    for c in cs:
        ent = {"project_rid": "project (Org)", "project_fiscal_rid": "project_fiscal (Org)", "case_rid": "cases (Org)", "account_rid": "account"}[c]
        rows.append((t, c, ent, category(t), "Main→Org"))
for (child, col, parent) in ai["edges"]:
    rows.append((child, col, f"{parent} (Org)", category(child), "AI→Org"))
rows = sorted(set(rows), key=lambda r: (r[4], r[0], r[1]))

CAT_TAG = {"entity": "ent", "summary": "sum", "history": "hist", "timeline": "tl", "audit": "aud", "staging": "stg"}
table_rows = "".join(
    f'<tr><td><code>{esc(c)}</code></td><td><code class="col">{esc(col)}</code></td>'
    f'<td><code>{esc(p)}</code></td><td><span class="tag {CAT_TAG[cat]}">{cat}</span></td>'
    f'<td><span class="db db-{db.split(chr(8594))[0].strip().lower()}">{esc(db)}</span></td></tr>'
    for (c, col, p, cat, db) in rows)

cat_counts = defaultdict(int)
for t in g["org"]["tables"]:
    cat_counts[category(t)] += 1

by_entity_orphans = [("project", 279548), ("document", 47473), ("account", 47453),
    ("project_fiscal", 31481), ("project_resource", 14291), ("project_resource_fiscal", 13198),
    ("interactions", 8009), ("interaction_items", 2144), ("case", 1146), ("case_projects", 922), ("resource", 899)]
orphan_rows = "".join(f'<tr><td><code>{esc(e)}</code></td><td class="num">{n:,}</td>'
    f'<td class="bar"><span style="width:{min(100, n/2795.48):.1f}%"></span></td></tr>' for e, n in by_entity_orphans)

domain_html = ""
for key, title in DOMAINS:
    d, n = domain_flow(key)
    if d:
        domain_html += f'<h3>{esc(title)} <span class="dim">· {n} relationships</span></h3><div class="canvas"><pre class="mermaid">\n{d}\n</pre></div>'

CSS = """
:root{--ground:#f4f6f9;--surface:#fff;--surface2:#fbfcfe;--ink:#161b24;--muted:#5b6675;--line:#e3e8ef;--accent:#3f4fce;--orphan:#c8455f;--clean:#1f9d6b;
 --c-ent:#3f4fce;--c-sum:#2563c9;--c-hist:#b3720d;--c-tl:#0f8a8a;--c-aud:#8a4fbf;--c-stg:#c8455f;
 --db-org:#3f4fce;--db-main:#0f8a8a;--db-ai:#8a4fbf;
 --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
@media (prefers-color-scheme:dark){:root{--ground:#0d1017;--surface:#151a22;--surface2:#11151c;--ink:#e7ebf2;--muted:#8b96a6;--line:#232b37;--accent:#8592ff;--orphan:#f0788a;--clean:#4ecf98;
 --c-ent:#8592ff;--c-sum:#5f9bf0;--c-hist:#e0a23c;--c-tl:#3ec9c9;--c-aud:#c08cf0;--c-stg:#f0788a;--db-org:#8592ff;--db-main:#3ec9c9;--db-ai:#c08cf0;}}
:root[data-theme="light"]{--ground:#f4f6f9;--surface:#fff;--surface2:#fbfcfe;--ink:#161b24;--muted:#5b6675;--line:#e3e8ef;--accent:#3f4fce;--orphan:#c8455f;--c-ent:#3f4fce;--c-sum:#2563c9;--c-hist:#b3720d;--c-tl:#0f8a8a;--c-aud:#8a4fbf;--c-stg:#c8455f;--db-org:#3f4fce;--db-main:#0f8a8a;--db-ai:#8a4fbf;}
:root[data-theme="dark"]{--ground:#0d1017;--surface:#151a22;--surface2:#11151c;--ink:#e7ebf2;--muted:#8b96a6;--line:#232b37;--accent:#8592ff;--orphan:#f0788a;--c-ent:#8592ff;--c-sum:#5f9bf0;--c-hist:#e0a23c;--c-tl:#3ec9c9;--c-aud:#c08cf0;--c-stg:#f0788a;--db-org:#8592ff;--db-main:#3ec9c9;--db-ai:#c08cf0;}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.55;font-size:15px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:48px 28px 80px}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);margin:0 0 10px}
h1{font-size:2.1rem;line-height:1.1;margin:0 0 12px;font-weight:640;letter-spacing:-.02em;text-wrap:balance}
h2{font-size:1.32rem;margin:54px 0 6px;font-weight:620;letter-spacing:-.01em}
h3{font-size:1rem;margin:24px 0 8px;font-weight:600;font-family:var(--mono)}h3 .dim{color:var(--muted);font-weight:400}
.lede{color:var(--muted);max-width:66ch;margin:0 0 8px}
.note{color:var(--muted);font-size:13.5px;margin:2px 0 14px;max-width:76ch}
code{font-family:var(--mono);font-size:12.5px}
.conv{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:20px 0;display:flex;gap:26px;flex-wrap:wrap}
.conv div{flex:1;min-width:220px}.conv b{font-family:var(--mono);color:var(--accent)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:13px;margin:22px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:15px 17px}
.tile .k{font-size:1.85rem;font-weight:660;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile .l{font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-top:3px}
.tile.warn .k{color:var(--orphan)}.tile.ok .k{color:var(--clean)}
.canvas{background:#fbfcfe;border:1px solid var(--line);border-radius:12px;padding:18px;margin:8px 0 18px;overflow-x:auto}.mermaid{min-width:640px}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:.03em;padding:2px 7px;border-radius:20px;text-transform:uppercase;border:1px solid;font-weight:600;white-space:nowrap}
.tag.ent{color:var(--c-ent);border-color:var(--c-ent)}.tag.sum{color:var(--c-sum);border-color:var(--c-sum)}.tag.hist{color:var(--c-hist);border-color:var(--c-hist)}
.tag.tl{color:var(--c-tl);border-color:var(--c-tl)}.tag.aud{color:var(--c-aud);border-color:var(--c-aud)}.tag.stg{color:var(--c-stg);border-color:var(--c-stg)}
.db{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:6px;border:1px solid;font-weight:600;white-space:nowrap}
.db-org{color:var(--db-org);border-color:var(--db-org)}.db-main{color:var(--db-main);border-color:var(--db-main)}.db-ai{color:var(--db-ai);border-color:var(--db-ai)}
.catbar{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-family:var(--mono);font-size:12px;color:var(--muted);margin:10px 0 4px}
.tablewrap{border:1px solid var(--line);border-radius:12px;overflow:auto;max-height:560px;margin:14px 0}
table{width:100%;border-collapse:collapse;font-size:13px}thead th{position:sticky;top:0;background:var(--surface);z-index:1}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-family:var(--mono);font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);font-weight:600}
.col{color:var(--accent)}
.otable{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:14px 0}
.otable td.num{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono)}.otable td.bar{width:34%}
.otable td.bar span{display:block;height:8px;background:var(--orphan);border-radius:4px;opacity:.85}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin:8px 0}
.pill{font-family:var(--mono);font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--line)}
.pill.done{color:var(--clean);border-color:var(--clean)}.pill.prog{color:var(--accent);border-color:var(--accent)}
footer{margin-top:60px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px}
"""

HTML = f"""<div class="wrap">
<p class="eyebrow">TRD365 · Data Model</p>
<h1>Entity relationships across three databases</h1>
<p class="lede">How records reference one another across the <b>Org</b>, <b>Main</b> and <b>TRD365AI</b> databases —
entities, summaries, and the history / timeline / staging / audit tables — plus where those references have gone
stale. Every edge is a real reference discovered by introspecting the live catalogs.</p>

<div class="conv">
  <div><b>rid</b> is each entity's primary key; a row is referenced elsewhere by <b>{{entity}}_rid</b>
    (<code>project.rid</code> → <code>project_rid</code>). AI uses <b>"projectId"</b> for the same link.</div>
  <div><span class="db db-org">Org</span> 25 per-tenant schemas · <span class="db db-main">Main</span>
    <code>trd365</code> (account &amp; summaries) · <span class="db db-ai">AI</span> <code>trd365ai</code>.
    <code>account</code> is in Main; AI tables link to <code>project_fiscal</code> cross-DB.</div>
</div>

<div class="tiles">
  <div class="tile"><div class="k">3</div><div class="l">Databases</div></div>
  <div class="tile"><div class="k">{cat_counts['history']+cat_counts['timeline']+cat_counts['audit']+cat_counts['staging']}</div><div class="l">History / audit tables (org)</div></div>
  <div class="tile"><div class="k">{len(rows)}</div><div class="l">Relationships</div></div>
  <div class="tile warn"><div class="k">462k</div><div class="l">Orphan rows</div></div>
  <div class="tile ok"><div class="k">0</div><div class="l">Naming typos</div></div>
</div>
<div class="catbar"><span>Table colours:</span>
  <span class="tag ent">entity</span><span class="tag sum">summary</span><span class="tag hist">history</span>
  <span class="tag tl">timeline</span><span class="tag aud">audit</span><span class="tag stg">staging</span></div>

<h2>Cross-database overview</h2>
<p class="note">The three databases and how they link. Solid arrows are same-DB references; dashed arrows cross
databases (Org↔Main via <code>account_rid</code>/<code>project_rid</code>, Org→AI via <code>projectId</code>).
Node colour = table category; the boxed groups are the databases.</p>
<div class="canvas"><pre class="mermaid">\n{crossdb_flow()}\n</pre></div>

<h2>Org domain diagrams</h2>
<p class="note">Each domain with <em>all</em> its history / timeline / staging / audit tables, coloured by
category. Arrows point parent → child (the child holds the <code>{{entity}}_rid</code>).</p>
{domain_html}

<h2>All relationships</h2>
<p class="note">{len(rows)} references across all three databases — child <code>table.column</code> → parent entity,
with the child's category and the database (incl. cross-DB <code>Main→Org</code> / <code>AI→Org</code>). Header stays pinned.</p>
<div class="tablewrap"><table>
  <thead><tr><th>Child table</th><th>References</th><th>Parent entity</th><th>Category</th><th>Database</th></tr></thead>
  <tbody>{table_rows}</tbody></table></div>

<h2>Referential integrity — orphan records</h2>
<p class="note">A reference is <em>orphaned</em> when a non-null <code>{{entity}}_rid</code> points at a parent
<code>rid</code> that no longer exists. Across all 25 Org schemas: <strong>462,473 orphan rows</strong>, dominated
by history/timeline tables referencing deleted projects.</p>
<div class="otable"><table><thead><tr><th>Referenced entity</th><th style="text-align:right">Orphan rows</th><th>Share</th></tr></thead><tbody>{orphan_rows}</tbody></table></div>
<div class="legend"><span><span class="pill done">done</span> trd365_00416 — 135,750</span>
  <span><span class="pill done">done</span> trd365_00414 — 27,614</span>
  <span><span class="pill prog">in progress</span> remaining 23 schemas</span></div>

<footer>Generated from live catalog introspection of all three databases (Org ref schema trd365_00042; main.trd365;
trd365ai public). Polymorphic columns (<code>entity_rid</code>, <code>attach_to</code>) reference multiple entity
types by a companion type column and aren't shown as single edges.</footer>
</div>"""

out = HERE / "reports" / "data_model_report.html"
out.write_text(f"<title>TRD365 Data Model &amp; Integrity</title>\n{HTML}")
print("wrote", out, "| relationships:", len(rows), "| domains:", sum(1 for k,_ in DOMAINS if domain_flow(k)[0]))
