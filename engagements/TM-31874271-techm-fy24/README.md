# TechM Canada FY24 — CRA SR&ED Audit Defence (case 31874271)

**PROTECTED B — client material. Do not distribute outside the Certainti.AI engagement team.**

Working folder for Tech Mahindra Limited's response to the CRA proposal letter of
July 30, 2026 on the FY2024 SR&ED claim (tax year-end 2024-03-31). Read
[`CONTEXT.md`](CONTEXT.md) first — it carries the case facts, the agreed strategy,
and the rules this engagement works under.

## What is here

| Path | What it is |
|---|---|
| `CONTEXT.md` | Case facts, agreed strategy (Path A), working rules. Authoritative. |
| `drafts/*.md` | The documents themselves. Markdown is the source of record — review and edit here. |
| `documents/*.docx` | House-formatted Word renderings of the drafts, for sending. Regenerate; do not hand-edit. |
| `build_docs.py` | Renders `drafts/` to `documents/` in the house format. |
| `verify_arithmetic.py` | Re-computes every figure in the CRA package. 20 checks, all passing. |
| `analyse_client_records.py` | Analyses the client records received Aug 26: timesheet coverage per project, narrative hours against system hours, and the rate actually applied per employee. Source files stay in the engagement bundle. |
| `TM_SRED_Audit_Defence_Report.html` | The full assessment as a shareable page — CRA position, verified arithmetic, options, project-by-project drill-down, lessons, process gates, timeline. Published as a private Artifact; sharing is a deliberate act from the page's share menu. |

The CRA source documents (proposal letter, Project Eligibility Report, Audit
Adjustments working paper, Summary of Adjustments, Schedules 1, 31, 508, T661)
are **not** kept in this repository. They live in the engagement bundle and in
the client file. Figures used here are transcribed into `verify_arithmetic.py`
with their source named.

## The drafts

| Draft | Audience | Status |
|---|---|---|
| `01_CRA_Extension_Request_Letter` | **CRA** — Kitty Leung, for Tech Mahindra signature | Ready to send once the placeholders are filled |
| `02_Call_Script_Kitty_Leung_INTERNAL` | **Internal only.** Never send to the CRA or the client | Ready |
| `03_Client_Brief_Heena_Shah` | **Client** — Tech Mahindra | Ready to send |
| `04_Line435_Recapture_Verification_Memo` | **Internal** | Complete for what the package permits |
| `05_Client_Records_Findings_Memo` | **Internal** | Complete — read before any submission |

Placeholders still to fill in draft 01: the date of the telephone call, and the
signatory's phone and email. Nothing else in that letter is provisional.

## Running the tooling

```bash
python3 verify_arithmetic.py    # exits non-zero if any reconciliation fails
python3 build_docs.py           # drafts/*.md -> documents/*.docx
```

Both need `python-docx` (`pip install python-docx`); the verifier needs nothing
beyond the standard library.

## Where the file stands

- Every figure in the CRA package reconciles. There is no arithmetic error to
  attack. See draft 04.
- The recovery ceiling, if Projects 3 to 7 were fully substantiated **and** then
  survived the eligibility review they have not yet had, is **$250,795** — 42.2%
  of the $594,399 at stake. No client-facing document may show a figure above it.
- The $175,850 at line 435 is imported from the 2023-03-31 reassessment and
  cannot be verified from this year's package. The FY2023 notice of reassessment
  is the single highest-value document still outstanding.
- **The records exist; the SR&ED split does not.** 846,994 rows of per-employee,
  per-day timesheet data cover all twelve months. But the claim applied a flat
  15% of salary on six projects and 50% on the seventh — the split was assumed,
  not measured. Never submit the timesheets without an allocation method, and
  never present a re-derived allocation as a contemporaneous record.
- Working from the line 435 figure, the FY2023 reassessment appears to have allowed
  roughly **37.6%** of the credit as filed — so the prior year was partially
  allowed, not denied in full. This corrects the "pattern of denial" framing in
  the internal report. It rests on an assumed 15% rate and must be confirmed.

## Rules that govern anything written here

- Never restate the section 244 mechanism claims — timestamp skew, message
  ordering, Kafka runtime uncertainty, schema-agnostic parsers, checkpoint
  markers, telemetry injection, anomaly clustering, adaptive script logic —
  without a mapped, dated contemporaneous artefact. The CRA has found in writing
  that they were not demonstrated.
- Every quantitative statement must reconcile to the CRA source documents.
- Honest framing always. No outcome is promised, and the credible-zero case is
  stated wherever the best case is.
- This is not legal or tax advice. Material submissions go to a Canadian SR&ED
  practitioner or tax counsel before filing.
