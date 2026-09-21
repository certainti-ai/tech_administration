---
eyebrow: CERTAINTI.AI
subtitle: SR&ED Advisory — Internal evidence assessment. Read before any onward transmission.
title: The Rogers Project 1 Additional Evidence — What It Proves, and Why Filing It Would Hurt
strapline: Tech Mahindra Limited | Reference case 31874271 | Tax year-end 2024-03-31 | Received September 21, 2026
---

> **The headline.** Five files from the Rogers project team. One duplicates what CRA already holds. Of the four that are new, none changes the eligibility position on Project 1, two would damage it if filed, and one contains a single thread worth pursuing. This is the strongest documentary record we have seen on Project 1 — and that is the problem. It is a strong record **of quality control**, and it belongs to Rogers and Openet rather than to Tech Mahindra.

## Bottom line

Five files. One duplicates what CRA already holds. Of the four that are new, **none changes the
eligibility position, two would damage it if filed, and one contains a single thread worth pursuing.**

This package is the strongest documentary record we have seen on Project 1. That is exactly the
problem: it is a strong record **of quality control**, and it is a record belonging to Rogers and
Openet rather than to Tech Mahindra.

## Inventory

| # | File | Origin | Status |
|---|------|--------|--------|
| 1 | `Wireless-Audit_CRA-Updated.pptx` | TM | **Duplicate** — CRA has it |
| 2 | `Rogers_RTRM_Test_Strategy_v0.2.docx` | Openet | **New — do not file** |
| 3 | `RTRM Core Adoption 23.09 to 24.06_Test cases_FInal_Approval.xlsx` | Rogers/TM | **New — do not file as-is** |
| 4 | `Core Adoption(NW-RTRM)-24.06.pptx` | Rogers | **New — one slide of value** |
| 5 | `JIRA TP REPORT & DEFECT REPORT -DASHBORDS.eml` | Rogers JIRA | **New — pursue the source, not the report** |

## 1. Wireless-Audit_CRA-Updated.pptx — already filed

Byte-different from the two copies we hold (the submission set and the OneDrive *Final Submission /
Technical* folder) but **textually identical to both** — a full slide-by-slide text diff returns
nothing. The hash differs only from repackaging. No new content. CRA has this.

## 2. Rogers_RTRM_Test_Strategy_v0.2.docx — filing this would hand CRA its conclusion

This is **Openet's document, not Tech Mahindra's**. The cover block reads *Client: Rogers · Title:
Openet Test Strategy · Issue Date 2020-07-07*. Version 0.2 is dated **2020-08-19**, authors Pei Ling
Ng and Oscar Ramirez. Stated audience: *"Openet development and testing teams."*

Three facts make it unusable:

- **Tech Mahindra is named zero times** in 23 pages. "Openet" appears 47 times, "Rogers" 22. Every
  cell in the *Responsible for test execution* table names Openet Test, Openet Dev or Rogers. Every
  CI/CD tool is *Setup By / Maintain By* Openet Dev or Openet QA.
- **It predates the claim year by three to four years.** It governs a 2020 solution build, not
  FY2024 work.
- **It defines success as conformance.** Exit criteria across every test stage: *"Test result as per
  the expected criteria"*, *"100% passed on Test Script & Test Case coverage"*, *"All business
  requirements have been met."*

That last point is the fatal one. Paragraph (f) of the s.248(1) definition excludes quality control —
work sustaining quality to satisfy *given* requirements — and routine testing. This document is a
written statement, by the client's own vendor, that the governing methodology of the project was
conformance to given requirements. The words **research, uncertainty, hypothesis, experiment,
prototype and investigation appear zero times each.**

## 3. Test case workbook — designs, not results

Eleven sheets; a 443-row *Test Summary*; roughly 310 test cases across Prov, Voice, Data, SMS, MMS,
Admin3-CUBIC, EMM and ED&A. Priority split P1 189 / P2 154 / P3 94. Largest feature groups: E2E
Validations 102, SMS with MCO 57, MMS with MCO 52, PPC 29.

The columns are **Test Case Name · Priority · Pre Condition · Description (Design Steps) · Expected
Result (Design Steps)**. There is **no actual-result column, no pass/fail, no execution date and no
tester**. These are test case *designs*.

The expected results carry pre-specified values — Result Code 2001, MCCMNC 302720, CC Time 10 mins,
Charge Type 1, RAT Type UTRAN/EUTRAN. **A prediction whose expected value is also the acceptance
criterion cannot fail in the way an experiment can.** This is good project documentation and poor
SR&ED evidence, and an RTA would read it the second way.

## 4. Core Adoption (NW-RTRM) deck — one slide worth keeping

Rogers-branded, created 8 August 2023, last modified 18 November 2024, 10 slides. Covers a four-week
QA window, *"Testing window From OCT 08 to Nov 08"* — inside FY2024. 260 RTRM-focused test cases
(P1 135 / P2 65 / P3 60).

Eight of ten slides are test coverage, out-of-scope items and risk registers — quality control on
their face, and the risk register reads as schedule and environment risk, not technological risk
(*"QA has 4 weeks window"*, *"Environmental downtime"*, *"Defect SLA Breach"*).

**Slide 7 is the exception and the only genuinely new technical content in the package:**

> REST-Assured based JAVA automation framework leveraging the Openet JMeter scripts for usage
> creation… **Enhanced/migrated the Openet JMeter framework** by adding system testing scenarios and
> to cater the downstream integration requirements… **Extend the automation framework to develop the
> utility to fetch the CDRs from huge numbers of CDRs file generated on remote systems.**

260 regression and 115 sanity scripts. This is tool development, and it is the one item here that
could be framed as eligible — but **only as support work under paragraph (d), and only if an eligible
core activity exists for it to attach to.** On its own it is a build, not an experiment. It does not
create a core; it needs one.

## 5. The JIRA / PowerBI report — the most substantive item, and it cuts against us

A PowerBI *Multi Test Plan Report* auto-generated from Rogers' JIRA and emailed **18 September 2026**
(three days ago) to a Rogers address, covering 22 test plan keys. Header: *"Last JIRA extract:
9/18/2026 8:45:03 AM."*

### What it establishes in our favour

A **contemporaneous system of record exists and can be queried.** 22 test plan keys (RTM-392136
through RTM-511086), a live defect dashboard, an execution Gantt with dated bars running Sep 10 to
Nov 12 with durations of 8 to 63 days, dated defect creation from late October through mid-June, and
dated executive summaries — one reads *"Status as of November 03, 2023."*

Against CRA's finding that *"the document does not contain evidence of an experiment, experimental
data or analysis of such data"*, this at least shows that dated, granular activity records exist.
That is more than we had. It answers the **fifth** SR&ED question (contemporaneous record).

### What it establishes against us

It does not touch questions one to four, and the summary figures affirmatively support CRA:

| Metric | Value |
|---|---|
| Pass Target / Pass Actual | 100% / **100%** |
| TERs in test plans / in scope / passed | 583 / 535 / 531 |
| **Failed TERs** | **0** |
| Blocked TERs | 0 |
| Descoped TERs | 48 |
| Open defects | **0 of 42 total** |
| Defect priority mix | P1 2 (5%) · P2 32 (76%) · P3 8 (19%) · P4 0 |
| Defect average resolution | 53 business hours |
| Blocker time | 0 business hours |
| P1 test cases passed | 296 of 310 (95%) |
| Automated test cases | 132 (23%) |
| Schedule | 0% behind, all 22 plans "Completed" |

The *Top 20 Opened and Deferred Defects* table is **empty** — there are none. The 14 P1 cases that did
not pass were **descoped, not failed**; nothing in 583 executions is recorded as a failure.

A Research and Technology Advisor reads a 100% pass rate against pre-specified expected results as
proof that the outcome was known in advance. A 53-business-hour average defect resolution with zero
blocker time describes a routine defect-fix cadence, not the resolution of a technological
uncertainty. **This is the Clevor fact pattern** — see authority F in the authorities memo.

### The second problem: whose SR&ED is this?

Every item in this package belongs to someone else. Rogers-branded deck; Rogers JIRA
(`jira.pbibot@rci.rogers.com`, `reqcentral.com`); Rogers SharePoint; Openet's governing test
strategy; Openet's tools; Tech Mahindra staff appearing in Rogers' directory with an **"- EXT"**
suffix, i.e. as external users on Rogers' project.

Advancing this as the proof of Project 1 invites the Advisor to ask **who bore the technological risk
and who was entitled to exploit the result.** That question is not open on the file today. This
evidence would open it, and it goes to whether Project 1 is Tech Mahindra's SR&ED at all rather than
contract work performed to a client's specification. That is a real downside, not a hypothetical one.

## The one live thread

**The JIRA keys are the asset. The dashboard is not.**

What could change the picture is not the summary — which is uniformly against us — but the underlying
defect records. Specifically:

1. **The 2 P1 defects**, in full: description, comment history, reassignments, time to close.
2. **The slowest-closing P2 defects** — those materially above the 53-business-hour average. The
   dashboard schema carries *Key · Priority · Status · OwningDir · Aging · Blocked · Application ·
   Summary · Created*, so aging is already a field and the pull is straightforward.
3. **The 48 descoped TERs** and why each was descoped. A test descoped because it *could not be
   performed* is closer to a limitation than an experiment, but the reasons are worth reading.

If any of those show a defect whose **cause was genuinely unknown**, where a sequence of hypotheses
was recorded and tested in the comment history, and where the resolution produced knowledge that
shaped later work — that is an experiment, with a contemporaneous record and a date, which is
precisely what CRA said was absent. It exists in JIRA or it does not, and a targeted pull would tell
us within a day.

Note the year boundary: the Gantt window (Sep–Nov) and the *"Status as of November 03, 2023"* summary
sit inside FY2024, but defects dated April through June fall into **FY2025**. Any extract must be
filtered to 1 April 2023 – 31 March 2024 before it is used on this file.

## Secondary value — hours allocation, not eligibility

CRA's financial finding is that *"there is no distinction between regular work and SR&ED work."*
If TERs and defects in JIRA carry assignees, this data is a route to a **defensible per-person
allocation for Project 1**, replacing the flat 15%. That does not rescue eligibility, and it is worth
nothing if eligibility fails. It is worth a great deal as a **process fix for FY2025 onward** — it
demonstrates that the records needed for a bottom-up allocation already exist in the client's
delivery systems and were simply never used to build the claim.

## Recommendation

**Do not send any of this to CRA.** Specifically:

- The Openet Test Strategy — dated 2020, names Openet and Rogers and not Tech Mahindra, and defines
  success as conformance to given requirements.
- The test case workbook as it stands — designs with pre-specified expected values and no results.
- The PowerBI dashboard — 100% pass, zero failures, zero open defects.
- The Wireless deck — CRA already holds it.

**Do** request the three targeted JIRA pulls above, filtered to the FY2024 window. Assess what comes
back before deciding whether anything from this package is filed.

Nothing here changes the recommended posture on Project 1, and nothing here changes the recovery
ceiling of $250,795.

---

*Not legal or tax advice. Any representation drawing on this should be settled by a Canadian SR&ED
practitioner or tax counsel before filing. PROTECTED B — client material; do not distribute outside
the Certainti.AI engagement team.*
