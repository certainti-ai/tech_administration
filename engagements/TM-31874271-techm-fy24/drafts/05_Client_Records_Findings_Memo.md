---
eyebrow: CERTAINTI.AI
subtitle: SR&ED Advisory — Internal findings memorandum. Read before any submission.
title: What the Client Records Show — and Why the Substantiation Strategy Must Change
strapline: Tech Mahindra Limited | Reference case 31874271 | Tax year-end 2024-03-31 | August 26, 2026
---

> **The headline.** The records exist, and they are better than we hoped: 846,994 rows of per-employee, per-day, per-project timesheet data from a PeopleSoft system, covering all twelve months of FY2024. But they do not contain the thing CRA actually asked for. The split between SR&ED and non-SR&ED work was never recorded — it was applied as a flat **15% of every employee's salary** on six of the seven projects, and a flat **50%** on the seventh. Submitting the timesheets without addressing this would hand CRA the proof that the allocation was assumed rather than measured.

## 1. What we received

Received August 26, 2026: the filed T661 project narratives for six project descriptions; six two-month PeopleSoft attendance exports covering April 2023 to March 2024; the FY2324 Canadian salary file; the R&D assessment workbook that built the claim, in its original and its August 24 revised form; the ITC computation for FY2023 and FY2024; eight signed subcontractor agreements; and nineteen subcontractor invoices.

All findings below are reproducible from `analyse_client_records.py` in this engagement folder. The source files stay in the engagement bundle — they are PROTECTED B and are not in this repository.

## 2. The binary question is answered — but the answer has two halves

### The records exist, and they are contemporaneous

The attendance exports carry, for every employee and every calendar day: employee id and name, project id and project name, attendance date, hours booked, timesheet approval status, work location, city, country and grade. The embedded SQL shows the source is a PeopleSoft Time and Labor installation (`ps_tl_rptd_time`, `ps_tm_tl_leave_sts`), with a manager approval workflow behind the status field.

That is genuine contemporaneous record-keeping, recorded daily during the year, at finer granularity than the monthly breakdown CRA asked for.

| Project | Hours | Of which approved | Employees | Months covered |
|---|---|---|---|---|
| P1 Rogers CBU Wireless | 79,173.8 | 43,244.8 | 48 | 12 |
| **P2 CBT Scotia QA Managed Service** | **0.0** | **0.0** | **0** | **0** |
| P3 Rogers QE Channels | 90,832.0 | 71,404.0 | 49 | 12 |
| P4 Rogers QE Media | 13,696.0 | 8,167.0 | 10 | 12 |
| P5 Rogers R4B 40633 | 7,921.0 | 3,900.0 | 6 | 12 |
| P6 Rogers R4B Digital | 4,332.0 | 3,412.0 | 3 | 12 |
| P7 Legacy Ticketing 38370 | 8,182.6 | 6,700.6 | 4 | 12 |

For P3 to P7 — the five projects denied purely for want of documentation — we can now produce exactly what the May 7 request asked for on the hours question: which employees worked on which project, month by month, from a system of record.

### What was never recorded is the SR&ED distinction

The R&D assessment workbook that produced the claim applies a single rate to every employee on a project:

| Project code | Rate applied | Employee rows |
|---|---|---|
| Y.IN2100170 (P1) | 15% | 96 |
| Y.IN2201961 (P2) | 15% | 169 |
| Y.IN2100171 (P3) | 15% | 64 |
| Y.IN2100190 (P4) | 15% | 26 |
| 40633 (P5) | 15% | 15 |
| Y.IN2301013 (P6) | 15% | 6 |
| 38370 (P7) | **50%** | 4 |

376 of 380 employee rows carry exactly 15%. The remaining four, all on P7, carry exactly 50%. There is no variation within any project, and the workbook labels the row `Net QRE %`.

The claim reconciles to this exactly. Every project's claimed salary is its total Canadian project payroll multiplied by that rate — P1 $4,088,153 × 15% = $613,223; P3 $3,162,194 × 15% = $474,329; P7 $279,708 × 50% = $139,854. The contract claim is the same: total subcontractor cost × 15% × a further 0.65 factor the workbook calls `SubCon QRE Adjustment` and does not explain. $3,125,657 × 15% × 0.65 = $304,752.

The SR&ED hours in the workbook were then derived *from* the percentage — available hours × 15% — rather than the percentage being derived from measured hours. The causality runs the wrong way for an audit.

**This is precisely what CRA wrote:** "There is no distinction between regular work and SR&ED work." On the current record that finding is not merely defensible — it is correct.

## 3. The narratives quote real hours, but describe them as something they are not

Five of the six filed narratives quote an hours figure in line 244. Every one of them reconciles exactly to the timesheet system:

| Narrative | Hours quoted | System total | |
|---|---|---|---|
| P1 Rogers CBU Wireless | 79,173.75 | 79,173.8 | matches |
| P3 Rogers QE Channels | 90,831.98 | 90,832.0 | matches |
| P4 Rogers QE Media | 13,696 | 13,696.0 | matches |
| P5 + P6 (one shared narrative) | 12,253 | 12,253.0 | matches |
| P7 Legacy Ticketing | 8,182.56 | 8,182.6 | matches |
| P2 CBT Scotia QA Managed Service | 1,823 | **0.0 — code absent** | no source |

This cuts both ways, and both directions matter.

**In our favour:** the hours in the narratives are real, system-sourced figures, not invention. That is worth knowing before anyone concludes the narratives were fabricated. They were not.

**Against us:** they are *total project hours*, and each narrative presents them as investigative effort. P3's narrative opens "The team spent approximately 90831.98 engineering hours across three investigative tracks." The claim itself asserts only 15% of that effort was SR&ED. The narrative therefore overstates the investigative effort by a factor of about seven against the company's own claim. The same mismatch exists on every project.

If CRA runs this comparison — and the Financial Reviewer has both documents — it reads as a claim that contradicts itself.

## 4. Project 2 has no hours behind it at all

Project code Y.IN2201961 does not appear anywhere in 846,994 rows of Canadian timesheet data. The claimant's own workbook records `Total Hours: 0` for it. Yet the project carries 169 employee rows and $548,729 of claimed salary — the second-largest salary line in the claim — and its narrative quotes 1,823 hours whose source we cannot locate.

This is consistent with what CRA found: a roughly 500-person managed service delivered mainly from India and Mexico, with Toronto coordinating. The Canadian time system has no hours booked to it.

**Recommendation: P2 moves from "concede on eligibility" to "concede without qualification."** It was already the weakest project on the technical findings. It is now also the weakest on substantiation, and it is the one project where a document request would produce nothing at all.

## 5. Contractors — better than we thought, but aimed at the wrong projects

Eight signed subcontractor agreements were provided, all with Canadian-incorporated suppliers: Vy Systems Canada Inc, XpertVantage Canada Inc, NextGen Consulting Inc, Pragra Incorporated, J & M Group Inc, TechDoQuest Incorporated, SAPSOL Technologies Inc. Canada, and TES Contract Services Inc. Canadian incorporation goes directly to the taxable-supplier test we were most worried about, and the workbook names each subcontractor individual with their cost.

The problem is coverage. All nineteen invoices are tagged to Y.IN2100170 (P1) or Y.IN2201961 (P2) — the two projects we intend to concede. **No invoice covers P3 through P6**, whose $166,574 of contract cost is the portion we intend to contest. And the unexplained 0.65 factor applies across all of it.

## 6. Two open items from the verification memo now close

**Line 429, the $77,698.** The FY2023 ITC worksheet carries the annotation "77698 — Used on line 429??" beside the FY2023 ORDTC of $113,095. The preparer applied the figure and flagged it with a double question mark. It does not tie to the FY2023 ORDTC or to anything else in the file. This is an unresolved preparer uncertainty, not a derivation we failed to find. Do not raise it with CRA until it is understood.

**The FY2023 basis.** The FY2023 worksheet confirms net eligible expenditures of $3,118,181.80 and a federal ITC of $467,727 at 15%. Our reverse-derivation of $3,118,180 from the credit was right to within two dollars, and the 15% rate assumption is confirmed for FY2023. The reassessed figure of $175,850 still requires the notice of reassessment — that document remains outstanding and remains the highest-value one.

## 7. What this means for the strategy

The recovery ceiling of $250,795 is unchanged as arithmetic. What has changed is the work needed to reach any part of it, and the risk attached to trying.

1. **We can answer the hours half of the May 7 request in full, for P3 to P7.** Per-employee monthly hours per project, from a system of record, reconciled to payroll. That is a real and deliverable improvement on the position CRA saw.
2. **We cannot produce a contemporaneous SR&ED/non-SR&ED split, because none was ever made.** Any split we submit now is a present-day technical judgment applied to historic records. It must be presented as exactly that, honestly labelled, and supported by a defensible method — employee by employee, against what the work actually involved. It must not be presented as a record.
3. **The 15% cannot be defended as a measurement, and should not be defended as one.** If a re-derived allocation supports something near 15% it will be because the technical review says so, not because the workbook said so. It may well come out lower.
4. **The 50% on P7 needs its own justification.** P7 was our second-priority contest on the strength of being salary-only and outside the ruled-against Rogers pattern. Four employees at a flat 50% now needs to be specifically supportable, or P7 becomes a liability rather than an asset.
5. **The narrative-versus-hours contradiction must be addressed before it is found.** Our representation should deal with it on our terms rather than wait for CRA to run the comparison.

## 8. Recommended next steps

1. Put the flat-rate finding in front of the client immediately. It changes what can honestly be claimed, and it is not a decision Certainti should take alone.
2. Do not submit the timesheet extracts on their own. Without an allocation method they demonstrate the very defect CRA identified.
3. Commission a technical review to build a defensible allocation for P3, P4, P5, P6 and P7 — the specific work, the specific people, the specific periods. Scope it to P3 and P7 first; together they are 29.3% of the credits at stake and carry the cleanest fact patterns.
4. Retrieve subcontractor invoices for P3 to P6, and establish what the 0.65 factor represents.
5. Concede P2 without qualification. Concede P1 unless the artefact hunt succeeds.
6. Obtain the FY2023 notice of reassessment, still outstanding.
7. Have tax counsel review the narrative-versus-claim contradiction specifically, before anything is filed. Our engagement rules already bar us from restating the section 244 mechanisms; this memo adds a second reason to be careful about what we affirm.

---

_Internal work product. Not legal or tax advice. The findings here are arithmetic and documentary; the characterisation of the allocation method and its consequences under the Income Tax Act should be confirmed by a Canadian SR&ED practitioner or tax counsel before any filing._
