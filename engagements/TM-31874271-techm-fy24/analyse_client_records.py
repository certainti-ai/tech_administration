#!/usr/bin/env python3
"""Analyse the client records received August 26, 2026.

Answers the question the whole FY2024 defence turned on: do per-employee,
per-project time records exist for Projects 3 to 7, and do they support the
amounts claimed?

Inputs (not in this repository — PROTECTED B, held in the engagement bundle):
  --timesheets   directory of CAN_*/*.xlsx PeopleSoft attendance exports
  --workbook     "Financial details for June 7 2026 response - revised Aug 24 2026.xlsx"
  --salary       "Canada_RD__FY2324_salary_data_final_list.xlsb"

The timesheet exports declare a single row in their <dimension> element, so
openpyxl's read_only mode stops after the header. This reads the sheet XML
directly instead.

Run:  python3 analyse_client_records.py --timesheets DIR --workbook XLSX --salary XLSB
"""

import argparse
import collections
import glob
import os
import re
import zipfile
from xml.etree.ElementTree import iterparse

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# CRA's project numbering, and the codes each maps to in the client's systems.
PROJECTS = [
    ("P1 Rogers CBU Wireless",     ["Y.IN2100170"], 613_223, 127_602),
    ("P2 CBT Scotia QA Managed",   ["Y.IN2201961"], 548_729,  10_576),
    ("P3 Rogers QE Channels",      ["Y.IN2100171"], 474_329,  20_992),
    ("P4 Rogers QE Media",         ["Y.IN2100190"], 108_344,  68_288),
    ("P5 Rogers R4B 40633",        ["40633"],        73_519,  53_718),
    ("P6 Rogers R4B Digital",      ["Y.IN2031013", "Y.IN2301013"], 18_139, 23_576),
    ("P7 Legacy Ticketing 38370",  ["38370"],       139_854,       0),
]

# Hours quoted in each filed T661 line 244 narrative, by CRA project number.
NARRATIVE_HOURS = {
    "P1 Rogers CBU Wireless": 79_173.75,
    "P2 CBT Scotia QA Managed": 1_823.0,
    "P3 Rogers QE Channels": 90_831.98,
    "P4 Rogers QE Media": 13_696.0,
    "P7 Legacy Ticketing 38370": 8_182.56,
    # P5 and P6 share one narrative quoting 12,253 hours between them.
}


def sheet_rows(path, title):
    """Yield rows from one sheet, ignoring the declared dimension."""
    z = zipfile.ZipFile(path)
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        buf = None
        for ev, el in iterparse(z.open("xl/sharedStrings.xml"), ("start", "end")):
            if el.tag == NS + "si":
                if ev == "start":
                    buf = []
                else:
                    strings.append("".join(buf)); el.clear()
            elif ev == "end" and el.tag == NS + "t" and buf is not None:
                buf.append(el.text or "")

    wb = z.read("xl/workbook.xml").decode("utf8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8")
    m = (re.search(r'<sheet[^>]*name="%s"[^>]*r:id="([^"]+)"' % re.escape(title), wb)
         or re.search(r'<sheet[^>]*r:id="([^"]+)"', wb))
    target = re.search(r'Id="%s"[^>]*Target="([^"]+)"' % re.escape(m.group(1)), rels).group(1)

    def col(ref):
        n = 0
        for ch in ref:
            if not ch.isalpha():
                break
            n = n * 26 + (ord(ch.upper()) - 64)
        return n - 1

    for ev, el in iterparse(z.open("xl/" + target.lstrip("/").replace("../", "")), ("end",)):
        if el.tag != NS + "row":
            continue
        cells = {}
        for c in el.findall(NS + "c"):
            v = c.find(NS + "v")
            kind = c.get("t")
            if kind == "inlineStr":
                # These exports write most values as inline strings, not into
                # the shared-string table.
                node = c.find(NS + "is")
                val = "".join(t.text or "" for t in node.iter(NS + "t")) if node is not None else ""
            elif v is None:
                val = ""
            elif kind == "s":
                val = strings[int(v.text)]
            else:
                val = v.text or ""
            cells[col(c.get("r", "A1"))] = val
        yield [cells.get(i, "") for i in range(max(cells) + 1)] if cells else []
        el.clear()


def strip_pad(code):
    """Project ids appear zero-padded to 15 characters in some exports."""
    code = str(code).strip()
    if code.endswith(".0"):
        code = code[:-2]
    return code.lstrip("0") or code


def read_timesheets(directory):
    """Hours, distinct employees and distinct months per claimed project."""
    lookup = {c: name for name, codes, _, _ in PROJECTS for c in codes}
    hours = collections.Counter()
    approved = collections.Counter()
    employees = collections.defaultdict(set)
    months = collections.defaultdict(set)
    total_rows = 0

    for path in sorted(glob.glob(os.path.join(directory, "*", "*.xlsx"))):
        it = sheet_rows(path, "Export Worksheet")
        header = next(it)
        ix = {h: i for i, h in enumerate(header)}
        for row in it:
            total_rows += 1
            get = lambda k: (row[ix[k]].strip() if k in ix and ix[k] < len(row) else "")
            name = lookup.get(strip_pad(get("PROJECT_ID")))
            if not name:
                continue
            try:
                effort = float(get("TIMESHEET_EFFORTS") or 0)
            except ValueError:
                effort = 0.0
            hours[name] += effort
            if effort > 0:
                employees[name].add(get("EMP_ID"))
                months[name].add(get("ATTED_DATE")[3:])
                if get("TIMESHEET_STATUS") == "Approved":
                    approved[name] += effort
    return hours, approved, employees, months, total_rows


def read_rates(workbook):
    """The SR&ED rate actually applied to each employee row in the claim."""
    rows = list(sheet_rows(workbook, "3- Emp Cost by Project"))
    head = next(i for i, r in enumerate(rows[:8]) if "Project Code" in r)
    ix = {v: i for i, v in enumerate(rows[head]) if v}
    by_project = collections.defaultdict(collections.Counter)
    for r in rows[head + 1:]:
        if not r or ix["Project Code"] >= len(r) or not r[ix["Project Code"]]:
            continue
        try:
            rate = round(float(r[ix["QRE"]]), 4)
        except (ValueError, IndexError):
            continue
        by_project[str(r[ix["Project Code"]]).strip()][rate] += 1
    return by_project


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesheets", required=True)
    ap.add_argument("--workbook", required=True)
    args = ap.parse_args()

    hours, approved, employees, months, total = read_timesheets(args.timesheets)
    print(f"Timesheet rows read: {total:,}\n")
    print(f"{'project':<28}{'hours':>11}{'approved':>11}{'emps':>6}{'months':>8}"
          f"{'narrative':>11}{'match':>7}")
    for name, _, _, _ in PROJECTS:
        quoted = NARRATIVE_HOURS.get(name)
        tick = ""
        if quoted is not None:
            tick = "yes" if abs(hours[name] - quoted) < 1 else "NO"
        print(f"{name:<28}{hours[name]:>11,.1f}{approved[name]:>11,.1f}"
              f"{len(employees[name]):>6}{len(months[name]):>8}"
              f"{(f'{quoted:,.0f}' if quoted else '—'):>11}{tick:>7}")

    p5p6 = hours["P5 Rogers R4B 40633"] + hours["P6 Rogers R4B Digital"]
    print(f"\nP5 + P6 share one narrative quoting 12,253 hours; system total {p5p6:,.1f}"
          f" ({'matches' if abs(p5p6 - 12253) < 1 else 'does NOT match'})")

    print("\nSR&ED rate applied per employee row in the claim workbook:")
    for project, counts in sorted(read_rates(args.workbook).items()):
        detail = ", ".join(f"{r:.0%} on {n} rows" for r, n in sorted(counts.items()))
        print(f"   {project:<14} {detail}")
    print("\nA single flat rate per project means the split between SR&ED and"
          "\nnon-SR&ED work was assumed, not measured.")


if __name__ == "__main__":
    main()
