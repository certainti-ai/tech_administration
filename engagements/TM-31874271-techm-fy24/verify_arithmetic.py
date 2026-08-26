#!/usr/bin/env python3
"""Independent re-computation of every figure in the CRA proposal package.

Case 31874271, Tech Mahindra Limited, tax year-end 2024-03-31. Sources are the
documents received 2026-07-29/30: proposal letter, Audit Adjustments working
paper (2026-07-22), Summary of Adjustments, and Schedules A-1, A-31, A-32
(T661) and A-508. The CRA figures below are transcribed from those documents;
everything else is computed here so the reconciliation can be re-run rather
than trusted.

Run:  python3 verify_arithmetic.py
"""

# Per-project amounts, from the Audit Adjustments working paper.
SALARIES = {
    "P1 Rogers CBU Wireless Y.IN2100170": 613_223,
    "P2 CBT Scotia QA Managed Service Y.IN2201961": 548_729,
    "P3 Rogers QE Channels Y.IN2100171": 474_329,
    "P4 Rogers QE Media Y.IN2100190": 108_344,
    "P5 Rogers R4B 40633": 73_519,
    "P6 Rogers R4B Digital Y.IN2031013": 18_139,
    "P7 Mt_Cc_Fp_Legacy_Ticketing #38370": 139_854,
}
CONTRACTS = {
    "P1 Rogers CBU Wireless Y.IN2100170": 127_602,
    "P2 CBT Scotia QA Managed Service Y.IN2201961": 10_576,
    "P3 Rogers QE Channels Y.IN2100171": 20_992,
    "P4 Rogers QE Media Y.IN2100190": 68_288,
    "P5 Rogers R4B 40633": 53_718,
    "P6 Rogers R4B Digital Y.IN2031013": 23_576,
    "P7 Mt_Cc_Fp_Legacy_Ticketing #38370": 0,
}

# Figures as stated by the CRA, transcribed from the package.
CRA = {
    "l300_salaries": 1_976_137,
    "l340_contracts": 304_752,
    "l380_allowable": 2_280_889,
    "l502_ppa": 1_086_875,
    "l511_subtotal": 3_367_764,
    "l529_20pct_contracts": 60_950,
    "l513_prov_assistance": 115_738,
    "l559_qualified": 3_191_076,
    "federal_itc": 478_661,
    "ordtc": 115_738,
    "ontario_pool": 3_306_814,
    "l429_prov_assistance": 77_698,
    "l435_filed": 467_727,
    "l435_revised": 175_850,
    "l442_filed": 1_735_464,
    "l442_revised": -175_850,
    "sch1_supp_assessed": 505_202,
    "sch1_supp_filed": 37_475,
    "sch1_supp_revised": 213_325,
    "sch1_l290_inducement": 36_389,
    "sch1_refund_interest": 1_086,
    "ni_assessed": 21_699_360,
    "ni_filed": 21_777_058,
    "ni_revised": 21_407_483,
    "ni_difference": 369_575,
    "credits_at_stake": 594_399,
}

PPA_RATE = 0.55        # prescribed proxy amount, T661 line 820
CONTRACT_HAIRCUT = 0.20  # T661 line 529
FEDERAL_ITC_RATE = 0.15  # non-CCPC / not a qualifying corporation, Sch 31
ORDTC_RATE = 0.035       # Schedule 508 Part 3

results = []


def check(label, computed, stated):
    ok = round(computed) == stated
    results.append((ok, label, computed, stated))
    return ok


def reconcile():
    salaries = sum(SALARIES.values())
    contracts = sum(CONTRACTS.values())
    allowable = salaries + contracts
    ppa = PPA_RATE * salaries
    subtotal = allowable + CRA["l502_ppa"]
    haircut = CONTRACT_HAIRCUT * contracts
    ontario_pool = CRA["l511_subtotal"] - CRA["l529_20pct_contracts"]
    ordtc = ORDTC_RATE * ontario_pool
    qualified = (CRA["l511_subtotal"] - CRA["l513_prov_assistance"]
                 - CRA["l529_20pct_contracts"])
    itc = FEDERAL_ITC_RATE * CRA["l559_qualified"]

    check("L300 salaries = sum of the seven projects", salaries, CRA["l300_salaries"])
    check("L340 contracts = sum of the seven projects", contracts, CRA["l340_contracts"])
    check("L380 allowable = L300 + L340", allowable, CRA["l380_allowable"])
    check("L820/502 prescribed proxy = 55% of salary base", ppa, CRA["l502_ppa"])
    check("L511 = L492 + L502", subtotal, CRA["l511_subtotal"])
    check("L529 = 20% of L340", haircut, CRA["l529_20pct_contracts"])
    check("Sch508 Ontario pool = L511 - L529", ontario_pool, CRA["ontario_pool"])
    check("Sch508 ORDTC = 3.5% of Ontario pool", ordtc, CRA["ordtc"])
    check("L559 qualified = L511 - L513 - L529", qualified, CRA["l559_qualified"])
    check("Sch31 federal ITC = 15% of qualified", itc, CRA["federal_itc"])
    check("Credits at stake = federal ITC + ORDTC",
          CRA["federal_itc"] + CRA["ordtc"], CRA["credits_at_stake"])

    # The pool and the recapture mechanic.
    check("L442 filed = L380 - L429 - L435",
          CRA["l380_allowable"] - CRA["l429_prov_assistance"] - CRA["l435_filed"],
          CRA["l442_filed"])
    check("L442 revised = 0 - 0 - L435 revised (negative pool -> income)",
          0 - CRA["l435_revised"], CRA["l442_revised"])

    # Schedule 1 supplemental additions across all three columns.
    other = CRA["sch1_l290_inducement"] + CRA["sch1_refund_interest"]
    check("Sch1 supplemental additions, assessed column",
          CRA["l435_filed"] + other, CRA["sch1_supp_assessed"])
    check("Sch1 supplemental additions, filed column", other, CRA["sch1_supp_filed"])
    check("Sch1 supplemental additions, revised column",
          CRA["l435_revised"] + other, CRA["sch1_supp_revised"])

    # Net income: remove the L118 add-back, add the L231 recapture, remove the
    # L411 deduction.
    check("Revised net income = filed - L118 + L231 + L411",
          CRA["ni_filed"] - CRA["l380_allowable"] + CRA["l435_revised"]
          + CRA["l442_filed"], CRA["ni_revised"])
    check("Net income difference, filed against revised",
          CRA["l380_allowable"] - CRA["l435_revised"] - CRA["l442_filed"],
          CRA["ni_difference"])
    check("Assessed net income - revised net income = L435 movement",
          CRA["ni_assessed"] - CRA["ni_revised"],
          CRA["l435_filed"] - CRA["l435_revised"])
    check("L435 movement", CRA["l435_filed"] - CRA["l435_revised"], 291_877)


def implied_fy2023():
    """What the revised L435 implies about the 2023-03-31 reassessment.

    Assumes the 15% non-refundable rate applied in FY2023 as it does here.
    Unverified until the FY2023 notice of reassessment is obtained.
    """
    return {
        "filed": CRA["l435_filed"] / FEDERAL_ITC_RATE,
        "reassessed": CRA["l435_revised"] / FEDERAL_ITC_RATE,
        "proportion_allowed": CRA["l435_revised"] / CRA["l435_filed"],
    }


def max_recovery(projects=("P3", "P4", "P5", "P6", "P7")):
    """Ceiling on credits recoverable if the named projects were fully restored."""
    pick = lambda d: sum(v for k, v in d.items() if k.split()[0] in projects)
    salaries, contracts = pick(SALARIES), pick(CONTRACTS)
    allowable = salaries + contracts
    subtotal = allowable + PPA_RATE * salaries
    pool = subtotal - CONTRACT_HAIRCUT * contracts
    ordtc = ORDTC_RATE * pool
    itc = FEDERAL_ITC_RATE * (pool - ordtc)
    return {
        "salaries": salaries, "contracts": contracts, "allowable": allowable,
        "ppa": PPA_RATE * salaries, "subtotal": subtotal,
        "contract_haircut": CONTRACT_HAIRCUT * contracts, "ontario_pool": pool,
        "ordtc": ordtc, "qualified": pool - ordtc, "federal_itc": itc,
        "total_credits": itc + ordtc,
    }


if __name__ == "__main__":
    reconcile()
    for ok, label, computed, stated in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label:<58} "
              f"computed {computed:>14,.2f}   stated {stated:>12,}")
    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks pass.")

    fy23 = implied_fy2023()
    print("\nImplied FY2023 position (assumes the 15% rate — UNVERIFIED):")
    print(f"  qualified expenditures as filed       {fy23['filed']:>12,.0f}")
    print(f"  qualified expenditures as reassessed  {fy23['reassessed']:>12,.0f}")
    print(f"  proportion allowed on reassessment    {fy23['proportion_allowed']:>12.1%}")

    rec = max_recovery()
    print("\nCeiling on recovery if Projects 3-7 were fully restored:")
    for key in ("salaries", "contracts", "allowable", "ppa", "subtotal",
                "contract_haircut", "ontario_pool", "ordtc", "qualified",
                "federal_itc", "total_credits"):
        print(f"  {key:<20} {rec[key]:>12,.0f}")
    print(f"  as a share of the {CRA['credits_at_stake']:,} at stake: "
          f"{rec['total_credits'] / CRA['credits_at_stake']:.1%}")

    raise SystemExit(1 if failed else 0)
