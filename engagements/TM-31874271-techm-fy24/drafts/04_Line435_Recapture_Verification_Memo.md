---
eyebrow: CERTAINTI.AI
subtitle: SR&ED Advisory — Internal verification memorandum
title: Independent Verification of the CRA Proposal Arithmetic, and the Line 435 Recapture
strapline: Tech Mahindra Limited | Reference case 31874271 | Tax year-end 2024-03-31 | August 26, 2026
---

> **Conclusion.** Every figure in the CRA proposal package that can be verified from within the package reconciles — twenty independent checks, all passing, including the $175,850 recapture mechanic and the $369,575 income adjustment. The package contains no arithmetic error we can attack. The single figure we cannot verify is the $175,850 itself, because it originates in the 2023-03-31 reassessment, and no FY2023 document is in the file. Obtaining that document is now the highest-value verification step outstanding.

## 1. Scope and sources

This memo verifies the arithmetic of the CRA package independently, rather than accepting it. Sources are the documents received July 29–30, 2026 under case 31874271: the proposal letter (PL E), the Project Eligibility Report signed July 16, 2026, the Audit Adjustments working paper dated July 22, 2026, the Summary of Adjustments, and Schedules A-1, A-31, A-32 (T661) and A-508. The checks are reproducible from `verify_arithmetic.py` in this engagement folder.

## 2. Checks performed and results

All twenty checks pass. Figures marked with a decimal are the exact computed value; the CRA figure is the rounded dollar amount.

| # | Check | Computed | Per CRA | Result |
|---|---|---|---|---|
| 1 | Line 300 salaries = sum of the seven project salaries | 1,976,137 | 1,976,137 | Pass |
| 2 | Line 340 contracts = sum of the seven project contract amounts | 304,752 | 304,752 | Pass |
| 3 | Line 380 allowable = line 300 + line 340 | 2,280,889 | 2,280,889 | Pass |
| 4 | Line 820 / 502 prescribed proxy = 55% of the salary base | 1,086,875.35 | 1,086,875 | Pass |
| 5 | Line 511 = line 492 + line 502 | 3,367,764 | 3,367,764 | Pass |
| 6 | Line 529 = 20% of line 340 | 60,950.40 | 60,950 | Pass |
| 7 | Schedule 508 Ontario pool = line 511 less line 529 | 3,306,814 | 3,306,814 | Pass |
| 8 | ORDTC = 3.5% of the Ontario pool | 115,738.49 | 115,738 | Pass |
| 9 | Line 559 qualified = 511 less 513 less 529 | 3,191,076 | 3,191,076 | Pass |
| 10 | Federal ITC = 15% of qualified expenditures | 478,661.40 | 478,661 | Pass |
| 11 | Total credits at stake = ITC + ORDTC | 594,399 | 594,399 | Pass |
| 12 | Line 442 as filed = 380 less 429 less 435 | 1,735,464 | 1,735,464 | Pass |
| 13 | Line 442 as revised = 0 less 0 less 175,850 | (175,850) | (175,850) | Pass |
| 14 | Schedule 1 supplemental additions, filed column | 37,475 | 37,475 | Pass |
| 15 | Schedule 1 supplemental additions, revised column | 213,325 | 213,325 | Pass |
| 16 | Schedule 1 supplemental additions, assessed column | 505,202 | 505,202 | Pass |
| 17 | Revised net income = filed, less line 118, plus line 231, plus line 411 | 21,407,483 | 21,407,483 | Pass |
| 18 | Net income difference, filed against revised | 369,575 | 369,575 | Pass |
| 19 | Assessed net income less revised net income | 291,877 | 291,877 | Pass |
| 20 | Line 435 movement, 467,727 to 175,850 | 291,877 | 291,877 | Pass |

Checks 19 and 20 are the useful pair: the gap between the currently assessed net income and the CRA's revised net income is exactly the movement in line 435. The recapture mechanic is internally consistent.

## 3. How the $175,850 recapture actually arises

The mechanic is worth stating precisely, because it is counter-intuitive and it will be misread otherwise.

1. Line 435 deducts, from the SR&ED expenditure pool, the investment tax credits applied or refunded in the **prior** year. As filed, that was $467,727 — the FY2023 credit.
2. The CRA has reduced line 435 to $175,850 because the FY2023 credit was itself reduced on reassessment. Standing alone, a **smaller** deduction is favourable: it leaves more in the pool.
3. But the CRA has simultaneously reduced total allowable expenditures to nil. The pool therefore becomes nil less $175,850, which is negative.
4. A negative pool is included in income. That is the $175,850 appearing at Schedule 1 line 231 in the revised column, and it is what drives the $369,575 increase in net income relative to the filed position.

So the income inclusion is not a penalty and not an independent adjustment. It is the arithmetic consequence of denying the current-year expenditures while a prior-year credit remains to be recovered. **It is also contingent:** if any material part of FY2024 expenditure is restored, the pool turns positive again and the income inclusion shrinks or disappears entirely. The value of contesting Projects 3 to 7 is therefore the credits recovered *plus* the removal or reduction of this inclusion. We have deliberately not put a dollar figure on the second component, because it depends on the deduction elected at line 460 in the restored scenario; it should be quantified with tax counsel once the substantiation position is known.

## 4. What the $175,850 implies about FY2023 — and why it matters strategically

Schedule 31 records that the corporation is not a qualifying corporation, so the non-refundable 15% rate applies. On the assumption that the same rate applied in FY2023:

| | Implied FY2023 qualified expenditures |
|---|---|
| At the credit as filed, $467,727 | approximately $3,118,180 |
| At the credit as reassessed, $175,850 | approximately $1,172,333 |
| Proportion allowed on reassessment | **approximately 37.6%** |

This is a materially different picture from the one the file has carried so far. FY2023 was **not** denied in full. Roughly $1.17 million of qualified expenditure survived reassessment in the immediately preceding year, on the same account and, in all likelihood, on overlapping project types.

Two consequences follow. First, our internal framing of "a pattern of denial" should be corrected to "a partial allowance followed by a proposed full denial" — the trajectory is worse, but the precedent is more useful than we had assumed. Second, if the FY2023 allowance covered work resembling any of Projects 3 to 7, that is a directly relevant precedent for the eligibility review that would follow substantiation. Neither point can be pressed until we see the FY2023 reassessment.

**This assumption must be tested, not relied upon.** If any part of the FY2023 credit was earned at a different rate, or if the reassessed figure reflects credits applied rather than credits earned, the implied expenditure figures change. The FY2023 notice of reassessment settles it.

## 5. The cross-year interaction, which cuts both ways

If an objection for FY2023 succeeds and the credit is restored toward $467,727, then — with FY2024 expenditures denied — the FY2024 line 435 deduction rises correspondingly, the negative pool deepens, and the FY2024 income inclusion rises from $175,850 toward $467,727. On a full restoration that is an additional $291,877 of FY2024 income, in the order of $77,000 of tax at a combined federal and Ontario rate of roughly 26.5%.

This is **not** an argument against objecting for FY2023. A full restoration recovers $291,877 of credit in FY2023 against roughly $77,000 of additional FY2024 tax; the net position is plainly favourable. It is an argument for coordinating the two years rather than running them independently, and for making sure the client is not surprised by an FY2024 bill arriving on the back of an FY2023 win. It also means our FY2024 representations must not assert anything about the FY2023 credit that a live FY2023 objection contradicts.

## 6. Items that cannot be verified from the package

| # | Item | Why it matters | How to resolve |
|---|---|---|---|
| 1 | The $175,850 itself | It is imported from FY2023 and is the basis of the entire income adjustment | Obtain the FY2023 notice of reassessment and the reassessed T661 and Schedule 31 |
| 2 | Status of the FY2023 year — final, under objection, or within the objection window | Determines whether the FY2024 figures are provisional and whether our positions can be consistent | Client tax function; the CRA Financial Reviewer may also confirm what is on the Agency's record |
| 3 | Line 429, provincial government assistance of $77,698 | Does not tie to any other figure in the package, and is not equal to the $115,738 ORDTC or the $36,389 income inclusion | Obtain the filed FY2024 T661 working papers and the derivation of this figure |
| 4 | Schedule 1 line 290, the 12(1)(x) inducement of $36,389 | Unchanged across the assessed, filed and revised columns. If it represents an income inclusion for a provincial credit that the CRA is now denying, it should arguably move too. Worth approximately $9,600 of tax | Establish which year's credit the inclusion relates to before raising it. Do not raise it speculatively |
| 5 | Whether the FY2024 credits were ever given effect | Schedule 31 shows $478,661 deducted from Part I tax in the filed column and nil in the assessed column, which suggests the claim was filed after the original assessment and the credit has not been paid or applied. If so, denial refuses a credit rather than recovering one, and there is no arrears interest exposure on it | Obtain the FY2024 notice of assessment and the account statement |

Items 3, 4 and 5 are each small or uncertain individually. They are listed because a submission that demonstrates command of the file is worth more than one that argues only the big number, and because item 5 changes how we describe the cash consequences to the client.

## 7. A note on the recovery ceiling

For completeness, the maximum recoverable from Projects 3 to 7 has been computed on the same basis the CRA uses:

| Step | Amount |
|---|---|
| Salaries, Projects 3 to 7 | $814,185 |
| Arm's-length contracts, Projects 3 to 6 | $166,574 |
| Total allowable expenditures | $980,759 |
| Prescribed proxy at 55% of salaries | $447,802 |
| Line 511 subtotal | $1,428,561 |
| Less 20% of contract expenditures | ($33,315) |
| Ontario pool | $1,395,246 |
| ORDTC at 3.5% | $48,834 |
| Qualified expenditures | $1,346,412 |
| Federal ITC at 15% | $201,962 |
| **Maximum credits recoverable** | **$250,795** |

This is 42.2% of the $594,399 at stake, and it assumes that every dollar is substantiated **and** survives an eligibility review that has not yet taken place. The internal report's stated best case of "$250–265K" should be tightened to approximately **$251,000**; $265,000 is above what the arithmetic permits from these five projects. No figure above $250,795 should appear in any client-facing document.

## 8. Recommended next steps

1. Obtain the FY2023 notice of reassessment. Everything in section 4 and section 5 is contingent on it, and it is a single document.
2. Establish the FY2023 objection status before filing anything for FY2024, so that the two years do not carry inconsistent positions.
3. Obtain the FY2024 notice of assessment and account statement to settle item 5 and the cash-consequence framing.
4. Record in the point-by-point template, at Section E, that the arithmetic has been verified and that only the FY2023-sourced figure remains open. The line 435 row of the Section A tracker can move from "Verify / accept" to "Verified internally; awaiting FY2023 documents".
5. Do not raise the line 429 or the 12(1)(x) queries with the CRA until they are understood. An unfounded query costs credibility we cannot presently spare.

---

_Internal work product. Not legal or tax advice. The verification here is arithmetic and structural; the legal characterisation of the recapture mechanic and of the cross-year interaction should be confirmed by a Canadian SR&ED practitioner or tax counsel before it is relied on in a filing._
