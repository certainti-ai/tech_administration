# CRA SR&ED Audit Defence — Tech Mahindra Limited (Case 31874271)

**Confidentiality: PROTECTED B client material. Do not share outputs outside the Certainti.AI engagement team.**

You are assisting the Certainti.AI SR&ED advisory team (CTO: Prabhu Balakrishnan) in defending Tech Mahindra Limited's FY2024 SR&ED claim against a CRA proposal to deny it in full. Read this file completely before doing anything; it is the authoritative context for this workspace.

## Case facts

| Field | Value |
|---|---|
| Claimant | Tech Mahindra Limited, 530 - 36 Toronto St, Toronto ON |
| Client contact | Heena Shah |
| Account # | 84935 7199 RC0002 |
| CRA reference case # | 31874271 |
| Tax year-end | 2024-03-31 |
| CRA proposal letter date | July 30, 2026 |
| **Response deadline** | **August 31, 2026** (extension request in progress — verify status before assuming) |
| CRA Financial Reviewer | Kitty Leung, 416-805-6591, Northern Ontario TSO |
| CRA Research & Technology Advisor | Tony Brunner, 416-428-0594 |
| RTM (approved PER) | Emmanuel Seitelbach |
| Submission channel | Submit Documents via My Business Account / Represent a Client (level 2 auth), case # 31874271 |

## What CRA proposes

Full denial. Filed → Revised: allowable SR&ED expenditures $2,280,889 → $0; qualified expenditures $3,191,076 → $0; federal ITC $478,661 → $0; ORDTC $115,738 → $0. Total credits at stake: **$594,399**. Line 435 also adjusted $467,727 → $175,850 because the **FY2023 year was already reassessed** (status of FY2023 objection: UNKNOWN — must be confirmed; treat FY2024 recapture math as provisional until then).

## The two failure modes (do not conflate them)

1. **Projects 1–2 — denied on eligibility after technical review.**
   - P1 Rogers CBU Wireless Y.IN2100170 ($613,223 salaries + $127,602 contracts): CRA found no technological uncertainty; work read as modernization/integration; CDR simulation read as QA against known requirements.
   - P2 CBT Scotia QA Managed Service Y.IN2201961 ($548,729 + $10,576): read as integration/configuration of existing QA tools (Appium/Selenium/Postman/LeanFT); 500-person multi-shore managed service.
   - **Critical credibility finding:** T661 section 244 narratives claimed mechanisms (timestamp skew, message ordering, Kafka runtime uncertainty, schema-agnostic parsers, checkpoint markers, telemetry injection, anomaly clustering, adaptive script logic, hypothesis-driven experimentation) that were NOT demonstrated in interviews and NOT present in submitted documentation (slides/screenshots only). Never re-argue these narratives without new dated contemporaneous artifacts.

2. **Projects 3–7 — denied purely on substantiation; NEVER reviewed for eligibility.**
   - P3 Rogers QE Channels Y.IN2100171: $474,329 + $20,992
   - P4 Rogers QE Media Y.IN2100190: $108,344 + $68,288
   - P5 Rogers R4B 40633: $73,519 + $53,718
   - P6 Rogers R4B Digital Y.IN2031013: $18,139 + $23,576
   - P7 Mt_Cc_Fp_Legacy_Ticketing #38370: $139,854 + $0
   - May 7, 2026 RFI asked for per-employee monthly hour breakdowns (SR&ED vs non-SR&ED, per project) and contractor support. Nothing was submitted for these five. All $304,752 of contractor costs across all seven projects is also entirely undocumented (no agreements, invoices, arm's-length or taxable-supplier evidence).

## Agreed strategy (Path A, sharpened)

- Request extension from Kitty Leung; confirm in writing via Submit Documents.
- **Contest P3–P7 substantiation** — the recoverable fight (~$250–265K best case, and only if records exist AND the projects then survive the follow-on eligibility review; four resemble P1's ruled-against pattern; P7 is the best conditional bet: salary-only, distinct fact pattern).
- **P1/P2: concede unless dated artifacts exist** for the specific section 244 mechanisms (strongest candidate: the undocumented 1-min vs 2-min CDR interval discovery and 6-second timing-buffer work on P1; the Appium↔Selenium pause/resume sync code history on P2).
- Administrative Review is a process-fairness remedy only, NOT an evidence do-over. The real second forum is a Notice of Objection within 90 days of any reassessment.
- The binary gating question: do per-employee, per-project time records for P3–P7 exist in any Tech Mahindra system (Jira, Clarity, SAP timesheets)? If genuinely no → recommend accepting FY2024 and investing in FY2025+ documentation instead.

## Repository layout

- `source_documents/` — CRA package: proposal letter (PL E), Project Eligibility Report (PER E, 10 pp), Audit Adjustments W/P, Summary of Adjustments, Schedules 1, 31, 508, T661. All PROTECTED B.
- `working_documents/` — Certainti internal: Response Strategy Memo; Point-by-Point Response Template (mirrors the PER; all amber input blocks are still EMPTY — filling them with client evidence is the core outstanding work).
- `deliverables/` — TM_SRED_Audit_Defence_Report.html: the full honest assessment (exec summary, CRA position, inventory, scenarios, per-project drill-downs P1–P7 with quality grades, lessons, 7 process gates, timeline). Treat its judgments as the current agreed position.

## Status — updated Aug 26, 2026

Drafted and ready in `drafts/` (rendered to `documents/`):

1. **Extension request letter to Kitty Leung** — draft 01, for Tech Mahindra signature. Placeholders: date of call, signatory phone and email. A companion internal call script is draft 02.
2. **Client brief for Heena Shah** — draft 03. Carries the binary records question with a 48-hour ask and a seven-item request list with owners and dates.
3. **Line 435 recapture arithmetic — verified independently.** Draft 04, reproducible via `verify_arithmetic.py`. Twenty checks, all passing; the package contains no arithmetic error to attack.

Two findings from the verification change the agreed position and are carried into the documents:

- **The recovery ceiling is $250,795, not $250–265K.** That is the exact maximum from Projects 3–7 if every dollar is substantiated and then survives an eligibility review. $265,000 is above what the arithmetic permits. No client-facing document may exceed $250,795.
- **FY2023 was partially allowed, not denied.** The revised line 435 of $175,850 implies roughly $1,172,333 of FY2023 qualified expenditure allowed against $3,118,180 filed — about 37.6%. This assumes the 15% rate and is unverified until the FY2023 notice of reassessment is in hand. It makes the prior year a more useful precedent than the "pattern of denial" framing in the deliverable report suggested.

## Client records received Aug 26, 2026 — the binary question is answered

Records arrived: filed T661 narratives (six documents covering the seven claimed projects — R4B and R4B Digital share one), twelve months of PeopleSoft timesheet exports, the FY2324 salary file, the R&D assessment workbook, the FY2023/FY2024 ITC computation, eight signed subcontractor agreements and nineteen invoices. Findings are in draft 05 and reproducible via `analyse_client_records.py`.

**The answer has two halves.** 846,994 rows of per-employee, per-day, per-project timesheet data exist, covering all twelve months, with a manager approval workflow. But the SR&ED/non-SR&ED split was never recorded: the claim applied a flat **15% of every employee's salary** on six projects and a flat **50%** on P7. 376 of 380 employee rows carry exactly 15%; the other four carry exactly 50%. Contracts are cost x 15% x an unexplained 0.65 factor. CRA's finding — "no distinction between regular work and SR&ED work" — is correct on the current record.

Rules that follow from this:

- **Never submit the timesheet extracts alone.** Without an allocation method they demonstrate the very defect CRA identified.
- **Never present a re-derived allocation as a contemporaneous record.** It is a present-day technical judgment on historic records and must be labelled as such.
- **Do not defend the 15% as a measurement.** A re-derived figure may come out lower.
- **P2 (Y.IN2201961) is now concede-without-qualification.** Zero hours in 846,994 rows; the claimant's own workbook records Total Hours: 0; yet 169 employee rows and $548,729 claimed.
- **P7's flat 50% needs its own justification** before P7 can be treated as the second-priority contest.
- **The narratives quote real system hours** (five of six reconcile exactly) but describe total project hours as investigative effort — roughly sevenfold overstatement against the company's own 15%. Address this on our terms before CRA finds it.
- Subcontractor agreements are all with Canadian-incorporated suppliers (good for the taxable-supplier test), but all nineteen invoices cover P1 and P2 only — nothing for P3–P6's $166,574.

Two open items closed: line 429's $77,698 is an unresolved preparer uncertainty annotated "Used on line 429??" in the client's own worksheet (still do not raise it with CRA); and the FY2023 basis is confirmed at $3,118,181.80 net eligible, $467,727 ITC at 15%.

## Still outstanding

1. Make the call to Kitty Leung, fill the letter placeholders, and submit the same day. A verbal extension that is never confirmed in writing protects nobody.
2. Obtain the **FY2023 notice of reassessment** and the objection status — the single highest-value document outstanding. Everything in draft 04 sections 4 and 5 is contingent on it.
3. Put the flat-rate finding to the client. It changes what can honestly be claimed and is not Certainti's decision to take alone.
4. Commission a technical review to build a defensible per-employee allocation, scoped to P3 and P7 first (together 29.3% of credits at stake, cleanest fact patterns).
5. Retrieve subcontractor invoices for P3–P6, and establish what the 0.65 factor represents.
4. P1/P2 artefact hunt before the contest/concede decision — the P1 CDR interval discovery and 6-second timing buffer, and the P2 Appium/Selenium sync code history, are the only candidates that might carry.
5. Obtain the FY2024 notice of assessment and account statement, to settle whether the FY2024 credits were ever given effect (see draft 04, section 6, item 5).
6. Feed the 7 process gates from the deliverable into Think R&D 365 evidence-readiness scoring.
7. Do not raise the line 429 ($77,698) or the 12(1)(x) ($36,389) queries with the CRA until they are understood. Unfounded queries cost credibility this file cannot spare.

## Working rules for this engagement

- Honest framing always: never present recovery above the ~$250–265K realistic best case; never promise outcomes.
- Never draft or submit anything restating section 244 mechanism claims without a mapped, dated artifact.
- Every quantitative statement must reconcile to the source PDFs in `source_documents/`.
- This team is not providing legal advice; material submissions should be reviewed by a Canadian SR&ED practitioner/tax counsel before filing.
