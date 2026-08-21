"""
Characterisation tests for the R&D percentage arithmetic.

These describe what ``entity-module/src/services/schemaService.ts`` does, not what
seems reasonable. Where the legacy JavaScript tool disagrees with it, the
disagreement is written down as a test so nobody "fixes" this back.

Every expected number here is worked out from the application's formulae by hand
in the test, so a test that agrees with the implementation because both share a
helper cannot happen.
"""

from __future__ import annotations

import pytest

from trd365_rd_percent import calculation as calc

COSTS = calc.Costs(fte=100_000.0, subcon=50_000.0, nonlabor=20_000.0)


class TestNetPercent:
    def test_it_is_the_adjustment_added_to_the_stored_potential(self):
        # schemaService.ts:4245 — netQre = qreAdjustment + existingPercent
        qre = calc.compute(potential_ai=60.0, adjustment=5.0, costs=COSTS)
        assert qre.net_percent == 65.0

    def test_a_negative_adjustment_reduces_it(self):
        qre = calc.compute(potential_ai=60.0, adjustment=-10.0, costs=COSTS)
        assert qre.net_percent == 50.0

    def test_it_is_not_rounded(self):
        # The application stores the raw sum. Rounding here would write a value it
        # never writes, which is the one thing this utility must not do.
        qre = calc.compute(potential_ai=33.33, adjustment=0.01, costs=COSTS)
        assert qre.net_percent == 33.33 + 0.01

    def test_a_negative_potential_is_refused(self):
        # schemaService.ts:4244 guards on this and then silently does nothing.
        # Silence is worse than an error for somebody running this by hand.
        with pytest.raises(calc.InconsistentInput, match="must be >= 0"):
            calc.compute(potential_ai=-1.0, adjustment=5.0, costs=COSTS)

    def test_zero_is_allowed(self):
        assert calc.compute(potential_ai=0.0, adjustment=0.0, costs=COSTS).net_percent == 0.0


class TestQualification:
    def test_a_positive_net_percentage_qualifies(self):
        assert calc.compute(potential_ai=1.0, adjustment=0.0, costs=COSTS).is_qualified is True

    def test_zero_does_not(self):
        # schemaService.ts:4271 — strictly greater than zero.
        assert calc.compute(potential_ai=0.0, adjustment=0.0, costs=COSTS).is_qualified is False

    def test_a_net_percentage_driven_negative_does_not(self):
        qre = calc.compute(potential_ai=10.0, adjustment=-20.0, costs=COSTS)
        assert qre.net_percent == -10.0
        assert qre.is_qualified is False


class TestTheSubContractorCap:
    """
    The first place the legacy JavaScript tool is wrong, and it overstates money.

    The application caps sub-contractor QRE at the jurisdiction's percentage
    (TRDV2-451, schemaService.ts:4267). index.js:553 omits the cap entirely.
    """

    def test_the_cap_is_applied_to_sub_contractor_cost(self):
        qre = calc.compute(
            potential_ai=50.0, adjustment=0.0, costs=COSTS, sub_con_percent=65.0
        )
        # 50_000 * 0.50 * 0.65
        assert qre.subcon == pytest.approx(16_250.0)

    def test_the_cap_does_not_touch_the_other_two(self):
        qre = calc.compute(
            potential_ai=50.0, adjustment=0.0, costs=COSTS, sub_con_percent=65.0
        )
        assert qre.fte == pytest.approx(50_000.0)  # 100_000 * 0.50
        assert qre.nonlabor == pytest.approx(10_000.0)  # 20_000 * 0.50

    def test_the_legacy_tool_would_have_written_half_again_as_much(self):
        # The size of the defect, stated so it is not mistaken for a rounding
        # difference. At the default 65% cap the legacy figure is 1/0.65 too big.
        capped = calc.compute(
            potential_ai=50.0, adjustment=0.0, costs=COSTS, sub_con_percent=65.0
        )
        legacy_would_be = COSTS.subcon * (50.0 / 100)
        assert legacy_would_be == pytest.approx(25_000.0)
        assert legacy_would_be / capped.subcon == pytest.approx(1 / 0.65)

    def test_a_hundred_percent_cap_is_a_no_op(self):
        # The only case in which the legacy tool happened to be right.
        qre = calc.compute(
            potential_ai=50.0, adjustment=0.0, costs=COSTS, sub_con_percent=100.0
        )
        assert qre.subcon == pytest.approx(COSTS.subcon * 0.50)

    def test_the_default_cap_is_the_applications_fallback(self):
        assert calc.FALLBACK_SUB_CON_PERCENT == 65.0
        qre = calc.compute(potential_ai=50.0, adjustment=0.0, costs=COSTS)
        assert qre.sub_con_percent == 65.0


class TestFinalCost:
    """
    The second place the legacy tool is wrong.

    The application sums the three components it just computed
    (schemaService.ts:4269). index.js:551 uses a fourth column, total_cost_prj.
    """

    def test_it_is_the_sum_of_the_three_components(self):
        qre = calc.compute(
            potential_ai=50.0, adjustment=0.0, costs=COSTS, sub_con_percent=65.0
        )
        assert qre.final == pytest.approx(qre.fte + qre.subcon + qre.nonlabor)
        assert qre.final == pytest.approx(50_000.0 + 16_250.0 + 10_000.0)

    def test_it_does_not_come_from_a_total_cost_column(self):
        # A project whose total_cost_prj disagrees with its components — which
        # nothing prevents — would make the legacy tool and the application write
        # different numbers into the same column.
        qre = calc.compute(
            potential_ai=50.0, adjustment=0.0, costs=COSTS, sub_con_percent=65.0
        )
        legacy_total_cost_prj = 170_000.0  # fte + subcon + nonlabor, uncapped
        assert qre.final != pytest.approx(legacy_total_cost_prj * 0.50)


class TestCostsFromARow:
    def test_null_costs_are_zero_not_an_error(self):
        # `?? 0` in the application (schemaService.ts:4247-4249).
        costs = calc.Costs.from_row(
            {"total_cost_fte_prj": None, "total_cost_subcon_prj": None}
        )
        assert (costs.fte, costs.subcon, costs.nonlabor) == (0.0, 0.0, 0.0)

    def test_numeric_strings_are_accepted(self):
        # psycopg2 hands back Decimal for numeric columns, and the application
        # parseFloat()s whatever it gets.
        costs = calc.Costs.from_row({"total_cost_fte_prj": "1234.56"})
        assert costs.fte == pytest.approx(1234.56)

    def test_a_missing_column_is_zero(self):
        assert calc.Costs.from_row({}).fte == 0.0

    def test_zero_costs_produce_zero_qre_but_can_still_qualify(self):
        # Qualification is about the percentage, not the money.
        qre = calc.compute(potential_ai=50.0, adjustment=0.0, costs=calc.Costs())
        assert qre.final == 0.0
        assert qre.is_qualified is True


class TestInputConsistency:
    """
    The caller supplies all three percentages; the application derives the third.

    So a caller can supply a combination the application could never produce, and
    writing it would leave a project whose final percentage does not equal its own
    potential plus its own adjustment.
    """

    def test_a_consistent_set_passes(self):
        calc.check_consistent(60.0, 5.0, 65.0)

    def test_an_inconsistent_set_is_refused(self):
        with pytest.raises(calc.InconsistentInput, match="is not rd_percent_potential_ai"):
            calc.check_consistent(60.0, 5.0, 70.0)

    def test_the_error_shows_the_arithmetic(self):
        with pytest.raises(calc.InconsistentInput) as raised:
            calc.check_consistent(60.0, 5.0, 70.0)
        assert "60.0 + 5.0 = 65.0" in str(raised.value)

    def test_a_display_rounded_final_is_tolerated(self):
        # Someone reading 65.00 off a screen and typing it back should not be
        # blocked by the last bit of a float.
        calc.check_consistent(59.995, 5.0, 65.0)

    def test_a_typo_is_not_tolerated(self):
        with pytest.raises(calc.InconsistentInput):
            calc.check_consistent(60.0, 5.0, 66.0)

    @pytest.mark.parametrize("final", [65.0 - 0.009, 65.0 + 0.009])
    def test_the_tolerance_is_a_hundredth_of_a_point(self, final):
        calc.check_consistent(60.0, 5.0, final)


class TestFidelityToTheApplication:
    def test_the_arithmetic_is_double_precision_like_the_source(self):
        # The application is TypeScript; its numbers are IEEE-754 doubles. Python
        # floats are the same doubles, so this reproduces its results exactly —
        # including the artefacts. Decimal would be tidier and would write values
        # the application never writes.
        qre = calc.compute(potential_ai=0.1, adjustment=0.2, costs=calc.Costs())
        assert qre.net_percent == 0.1 + 0.2
        assert qre.net_percent != 0.3
