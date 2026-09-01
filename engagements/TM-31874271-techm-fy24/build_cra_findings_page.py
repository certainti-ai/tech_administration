#!/usr/bin/env python3
"""Render CRA_findings_verbatim.md as a standalone reference page.

The Agency's text is read from the markdown rather than retyped, so the page
and the file cannot drift apart. Our own apparatus — the contents rail, the
provenance lines, the transcription note — is added around it in a different
typeface so a reader always knows whose words they are looking at.
"""
import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "CRA_findings_verbatim.md"
OUT = HERE / "CRA_Findings_Case_31874271.html"

# Provenance shown under each top-level heading, keyed by its opening words.
PROVENANCE = {
    "Project Eligibility Report":
        "Tony Brunner, Research and Technology Advisor · approved by Emmanuel Seitelbach, "
        "Research and Technology Manager · Northern Ontario TSO · 16 July 2026",
    "Audit Adjustments working paper":
        "Kitty Leung, Financial Reviewer · 22 July 2026",
    "Proposal letter":
        "Kitty Leung, Financial Reviewer · Business Tax Incentive Programs · 30 July 2026",
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def inline(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r'<code>\1</code>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


FIG_ROW = re.compile(r"^(.+?) \$ ([\d,]+) \$ ([\d,]+) \$ ([\d,]+)$")


def paragraphs(paras):
    """Render CRA paragraphs, lifting the adjustment figures into a real table."""
    out, table = [], []

    def flush():
        if not table:
            return
        out.append('<div class="tablewrap"><table>')
        out.append("<thead><tr><th>Line item</th><th>Filed</th>"
                   "<th>Revised by CRA</th><th>Difference</th></tr></thead><tbody>")
        for label, a, b_, c in table:
            out.append(f"<tr><td>{inline(label)}</td><td>${a}</td>"
                       f"<td>${b_}</td><td>${c}</td></tr>")
        out.append("</tbody></table></div>")
        table.clear()

    for p in paras:
        m = FIG_ROW.match(p)
        if m:
            table.append(m.groups())
            continue
        flush()
        if p.startswith("Documentation:"):
            out.append('<p class="sublabel">Documentation</p>')
        elif p.startswith("Filed Revised by CRA Difference"):
            continue
        else:
            cls = ""
            if "does not meet the definition of SR&ED" in p or p.startswith("No contracts claimed"):
                cls = ' class="verdict"'
            out.append(f"<p{cls}>{inline(p)}</p>")
    flush()
    return out


def parse(md):
    """Split the markdown into (level, heading, [paragraphs]) blocks."""
    blocks, cur = [], None
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            cur = {"level": 2, "title": line[3:].strip(), "paras": []}
            blocks.append(cur)
        elif line.startswith("### "):
            cur = {"level": 3, "title": line[4:].strip(), "paras": []}
            blocks.append(cur)
        elif line.startswith("#") or line.startswith("---"):
            continue
        elif line.strip() and cur is not None:
            cur["paras"].append(line.strip())
    return blocks


def render(blocks, note):
    nav, body = [], []
    for b in blocks:
        sid = slug(b["title"])
        if b["level"] == 2:
            nav.append(f'<a class="nav-h" href="#{sid}">{inline(b["title"])}</a>')
            prov = next((v for k, v in PROVENANCE.items() if b["title"].startswith(k)), "")
            body.append(f'<section id="{sid}" class="doc">')
            body.append(f'<h2>{inline(b["title"])}</h2>')
            if prov:
                body.append(f'<p class="prov">{inline(prov)}</p>')
            if b["paras"]:
                body.append("<blockquote>")
                body.extend(paragraphs(b["paras"]))
                body.append("</blockquote>")
            body.append("</section>")
            continue

        # A determination section: CRA's own numbering leads.
        num, _, rest = b["title"].partition(" — ")
        nav.append(f'<a class="nav-s" href="#{sid}">'
                   f'<span class="nav-num">{inline(num)}</span>'
                   f'<span>{inline(rest or num)}</span></a>')
        body.append(f'<section id="{sid}" class="finding">')
        body.append('<div class="fhead">'
                    f'<span class="fnum">{inline(num)}</span>'
                    + (f'<h3>{inline(rest)}</h3>' if rest else "") +
                    '</div>')
        body.append('<blockquote>')
        body.extend(paragraphs(b["paras"]))
        body.append("</blockquote>")
        body.append("</section>")
    return "\n".join(nav), "\n".join(body), note


def main():
    md = SRC.read_text()
    note = " ".join(
        l.strip() for l in md.splitlines()[4:7] if l.strip()
    )
    nav, body, note = render(parse(md), note)
    OUT.write_text(TEMPLATE.format(nav=nav, body=body, note=html.escape(note)))
    print(f"wrote {OUT.name} ({OUT.stat().st_size:,} bytes)")


TEMPLATE = """<title>Case 31874271 Findings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{
  --paper:#F7F8F9; --sheet:#FFFFFF; --sunk:#F1F3F5;
  --ink:#16191D; --ink-2:#5A6068; --ink-3:#878D95;
  --rule:#DFE3E7; --rule-2:#C9CFD5;
  --classification:#8C2A2A; --classification-bg:#F7ECEC;
  --seal:#2E4A62; --seal-soft:#EAEFF4;
  --measure:66ch;
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    --paper:#111417; --sheet:#1A1E22; --sunk:#22272C;
    --ink:#E4E7EA; --ink-2:#A2A9B1; --ink-3:#7C838B;
    --rule:#2C3238; --rule-2:#3A424A;
    --classification:#D98A8A; --classification-bg:#2A1D1D;
    --seal:#8FB0C9; --seal-soft:#1E2A34;
  }}
}}
:root[data-theme="dark"]{{
  --paper:#111417; --sheet:#1A1E22; --sunk:#22272C;
  --ink:#E4E7EA; --ink-2:#A2A9B1; --ink-3:#7C838B;
  --rule:#2C3238; --rule-2:#3A424A;
  --classification:#D98A8A; --classification-bg:#2A1D1D;
  --seal:#8FB0C9; --seal-soft:#1E2A34;
}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"Source Serif 4",Georgia,"Times New Roman",serif;
  font-size:16.5px; line-height:1.62; -webkit-font-smoothing:antialiased;
}}
code{{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;
  background:var(--sunk);padding:1px 5px;border-radius:3px}}
:focus-visible{{outline:2px solid var(--seal);outline-offset:3px;border-radius:2px}}

/* classification bands — the real document carries these */
.band{{
  font-family:"IBM Plex Sans",system-ui,sans-serif; font-size:10.5px; font-weight:600;
  letter-spacing:.2em; text-transform:uppercase; text-align:center;
  color:var(--classification); background:var(--classification-bg);
  padding:8px 16px; border-block:1px solid var(--rule);
}}

.wrap{{max-width:1180px;margin:0 auto;padding:0 24px;display:flex;gap:52px;align-items:flex-start}}
@media(max-width:960px){{.wrap{{display:block;padding:0 18px}}}}

/* contents rail — CRA's own numbering */
nav{{
  position:sticky; top:0; width:236px; flex-shrink:0; padding:40px 0 40px;
  max-height:100vh; overflow-y:auto;
  font-family:"IBM Plex Sans",system-ui,sans-serif;
}}
@media(max-width:960px){{nav{{position:static;width:auto;max-height:none;padding:26px 0 6px;border-bottom:1px solid var(--rule)}}}}
nav .rail-label{{font-size:9.5px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;
  color:var(--ink-3);padding-bottom:12px;border-bottom:1px solid var(--rule);margin-bottom:12px}}
nav a{{display:block;text-decoration:none;color:var(--ink-2)}}
nav a:hover{{color:var(--ink)}}
.nav-h{{font-size:12.5px;font-weight:600;color:var(--ink);margin:16px 0 6px;line-height:1.35}}
.nav-h:first-of-type{{margin-top:0}}
.nav-s{{display:flex;gap:9px;font-size:12.3px;padding:4px 0;line-height:1.4}}
.nav-num{{font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--seal);flex-shrink:0;padding-top:1px}}

main{{flex:1;min-width:0;background:var(--sheet);border-inline:1px solid var(--rule);
  padding:52px 56px 72px;margin-bottom:0}}
@media(max-width:960px){{main{{padding:34px 22px 52px;border-inline:0}}}}

header.masthead{{border-bottom:2px solid var(--ink);padding-bottom:22px;margin-bottom:8px}}
.eyebrow{{font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:10px;font-weight:600;
  letter-spacing:.2em;text-transform:uppercase;color:var(--seal);margin:0 0 10px}}
h1{{margin:0;font-size:31px;font-weight:600;line-height:1.18;letter-spacing:-.01em;text-wrap:balance}}
.subject{{font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:13.5px;color:var(--ink-2);
  margin:12px 0 0;max-width:var(--measure)}}
.facts{{display:flex;flex-wrap:wrap;gap:10px 30px;margin-top:20px;
  font-family:"IBM Plex Sans",system-ui,sans-serif}}
.facts div{{display:flex;flex-direction:column;gap:2px}}
.facts .k{{font-size:9.5px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}}
.facts .v{{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink)}}

.note{{font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:12.3px;line-height:1.6;
  color:var(--ink-2);background:var(--sunk);border-left:2px solid var(--rule-2);
  padding:13px 16px;margin:26px 0 0;max-width:var(--measure)}}

section.doc{{margin-top:52px;padding-top:22px;border-top:1px solid var(--rule)}}
section.doc h2{{margin:0;font-size:20px;font-weight:600;letter-spacing:-.01em;text-wrap:balance}}
.prov{{font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:12px;color:var(--ink-2);
  margin:7px 0 0;max-width:var(--measure)}}

section.finding{{margin-top:34px;scroll-margin-top:16px}}
.fhead{{display:flex;gap:13px;align-items:baseline;margin-bottom:13px}}
.fnum{{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:500;color:var(--seal);
  background:var(--seal-soft);padding:3px 8px;border-radius:3px;flex-shrink:0;white-space:nowrap}}
.fhead h3{{margin:0;font-size:16px;font-weight:600;line-height:1.3;text-wrap:balance}}

blockquote{{margin:0;padding-left:20px;border-left:1px solid var(--rule-2)}}
blockquote p{{margin:0 0 14px;max-width:var(--measure)}}
blockquote p:last-child{{margin-bottom:0}}
.sublabel{{font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:10px;font-weight:600;
  letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin:20px 0 8px !important}}
p.verdict{{color:var(--classification);font-weight:600}}

.tablewrap{{overflow-x:auto;margin:16px 0 18px;max-width:var(--measure)}}
table{{border-collapse:collapse;width:100%;font-family:"IBM Plex Sans",system-ui,sans-serif;
  font-size:12.8px;font-variant-numeric:tabular-nums;min-width:440px}}
th{{text-align:right;font-size:9.5px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink-3);padding:0 0 7px 16px;border-bottom:1px solid var(--rule-2)}}
th:first-child{{text-align:left;padding-left:0}}
td{{text-align:right;padding:7px 0 7px 16px;border-bottom:1px solid var(--rule);color:var(--ink)}}
td:first-child{{text-align:left;padding-left:0;color:var(--ink-2)}}
tr:last-child td{{border-bottom:0}}
footer{{font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:11.5px;color:var(--ink-3);
  line-height:1.6;margin-top:52px;padding-top:20px;border-top:1px solid var(--rule);max-width:var(--measure)}}
@media (prefers-reduced-motion: reduce){{*{{transition:none!important;scroll-behavior:auto!important}}}}
</style>

<div class="band">Protected B — Protégé B</div>

<div class="wrap">
<nav>
  <div class="rail-label">Contents</div>
  {nav}
</nav>

<main>
  <header class="masthead">
    <p class="eyebrow">Canada Revenue Agency · verbatim record</p>
    <h1>Findings on the FY2024 SR&amp;ED claim</h1>
    <p class="subject">The Agency's own words, as written. Reproduced so the determinations can be
    read and quoted without returning to the source PDFs.</p>
    <div class="facts">
      <div><span class="k">Claimant</span><span class="v">Tech Mahindra Limited</span></div>
      <div><span class="k">Reference case</span><span class="v">31874271</span></div>
      <div><span class="k">Account</span><span class="v">84935 7199 RC0002</span></div>
      <div><span class="k">Tax year-end</span><span class="v">2024-03-31</span></div>
      <div><span class="k">Package received</span><span class="v">2026-07-29</span></div>
    </div>
  </header>

  <p class="note">{note}</p>

  {body}

  <footer>
    Everything above is the Canada Revenue Agency's text, not Certainti's assessment of it.
    Our analysis of these findings is a separate document.
    <br><br>
    <strong>Protected B — client material.</strong> Do not distribute outside the
    Certainti.AI engagement team.
  </footer>
</main>
</div>

<div class="band">Protected B — Protégé B</div>
"""

if __name__ == "__main__":
    main()
