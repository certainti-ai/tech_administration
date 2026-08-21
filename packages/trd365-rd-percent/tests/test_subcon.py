"""
Resolving the sub-contractor cap.

Four of the five outcomes are fallbacks the application logs and continues from,
so a project can be sitting on any of them with real stored numbers computed that
way. Each is reproduced, and each is tested — a fallback that silently differs
from the application's is a wrong number nobody notices.
"""

from __future__ import annotations

import json

import pytest

from trd365_rd_percent import subcon
from trd365_rd_percent.calculation import FALLBACK_SUB_CON_PERCENT

USA = "P001-country-usa"


def fetcher(rows):
    captured = {}

    def fetch(query, params):
        captured["query"] = query
        captured["params"] = params
        return rows

    fetch.captured = captured
    return fetch


def config(code="USA", percent=42.0, start="2024-01-01", end="2026-12-31", key=None):
    chosen = key or subcon.SUB_CON_PERCENT_KEY_BY_COUNTRY_CODE.get(code, "sub_con_percent")
    payload = {chosen: percent}
    return (code, json.dumps(payload), start, end)


def resolve(rows, *, fiscal_year=2025, start="04/01", end="03/31", country=USA):
    return subcon.resolve(
        fetcher(rows),
        country_rid=country,
        fiscal_year=fiscal_year,
        account_fiscal_start=start,
        account_fiscal_end=end,
    )


class TestTheFallbacks:
    def test_no_country_falls_back(self):
        found = resolve([config()], country=None)
        assert found.percent == FALLBACK_SUB_CON_PERCENT
        assert "no country" in found.reason

    def test_no_account_fiscal_dates_falls_back(self):
        found = resolve([config()], start=None)
        assert found.percent == FALLBACK_SUB_CON_PERCENT
        assert found.is_fallback

    def test_no_configuration_for_the_country_falls_back(self):
        found = resolve([])
        assert found.percent == FALLBACK_SUB_CON_PERCENT
        assert "no Federal R&D Credit configuration" in found.reason

    def test_a_missing_key_in_the_configuration_falls_back(self):
        found = resolve([config(key="something_else")])
        assert found.percent == FALLBACK_SUB_CON_PERCENT
        assert "missing or not a number" in found.reason

    def test_a_non_numeric_value_falls_back(self):
        found = resolve([("USA", json.dumps({"rrc_sub_con_percent": "n/a"}), None, None)])
        assert found.percent == FALLBACK_SUB_CON_PERCENT

    def test_the_fallback_is_never_zero(self):
        # constants.ts:38-41 is explicit about this: it must never silently zero
        # out subcon QRE. A zero cap would write zero sub-contractor QRE, which
        # looks like a real answer.
        assert FALLBACK_SUB_CON_PERCENT > 0


class TestResolution:
    def test_a_covering_configuration_is_used(self):
        found = resolve([config(percent=42.0)])
        assert found.percent == 42.0
        assert found.reason == "configured"
        assert found.is_fallback is False

    def test_the_most_recent_covering_configuration_wins(self):
        # The query orders by effective_start_date DESC, so the first overlap is
        # the most recent applicable one.
        rows = [
            config(percent=50.0, start="2025-01-01", end="2027-12-31"),
            config(percent=40.0, start="2020-01-01", end="2030-12-31"),
        ]
        assert resolve(rows).percent == 50.0

    def test_with_no_overlap_the_most_recent_is_used_anyway(self):
        # Deliberate in the application: a stale cap is closer to right than a flat
        # constant. But the reason has to say so, because the number is not the
        # configured one for that year.
        found = resolve([config(percent=33.0, start="2010-01-01", end="2011-12-31")])
        assert found.percent == 33.0
        assert "no configuration covers fiscal 2025" in found.reason
        assert found.is_fallback

    def test_an_open_ended_window_still_applies(self):
        assert resolve([config(percent=44.0, start="2020-01-01", end=None)]).percent == 44.0

    def test_an_open_start_still_applies(self):
        assert resolve([config(percent=44.0, start=None, end="2030-01-01")]).percent == 44.0

    def test_a_configuration_json_object_is_accepted_as_well_as_a_string(self):
        # psycopg2 decodes jsonb to dict; the original handles both.
        rows = [("USA", {"rrc_sub_con_percent": 37.5}, "2024-01-01", "2026-12-31")]
        assert resolve(rows).percent == 37.5


class TestTheCountryKey:
    def test_the_united_states_uses_the_regular_research_credit_key(self):
        # constants.ts:34 — a product decision: RRC, not ASC.
        assert subcon.SUB_CON_PERCENT_KEY_BY_COUNTRY_CODE["USA"] == "rrc_sub_con_percent"
        both = json.dumps({"rrc_sub_con_percent": 20.0, "sub_con_percent": 99.0})
        rows = [("USA", both, None, None)]
        assert resolve(rows).percent == 20.0

    def test_canada_uses_its_own_key(self):
        # constants.ts:35 — the Canadian federal programme has no sub_con_percent.
        rows = [("CAN", json.dumps({"subcon_qre_adjustment": 30.0}), None, None)]
        assert resolve(rows).percent == 30.0

    def test_any_other_country_uses_the_default_key(self):
        rows = [("GBR", json.dumps({"sub_con_percent": 55.0}), None, None)]
        assert resolve(rows).percent == 55.0


class TestTheQuery:
    def test_it_asks_only_for_active_federal_country_wide_configurations(self):
        fetch = fetcher([config()])
        subcon.resolve(
            fetch,
            country_rid=USA,
            fiscal_year=2025,
            account_fiscal_start="04/01",
            account_fiscal_end="03/31",
        )
        query = fetch.captured["query"]
        assert "is_federal = true" in query
        assert "state_rid IS NULL" in query
        assert "status_description = 'active'" in query
        assert "ORDER BY rv.effective_start_date DESC" in query

    def test_the_country_is_a_parameter_not_interpolated(self):
        # The original builds this query by string concatenation. Parameterising it
        # costs nothing and removes the question entirely.
        fetch = fetcher([config()])
        subcon.resolve(
            fetch,
            country_rid="'; DROP SCHEMA trd365; --",
            fiscal_year=2025,
            account_fiscal_start="04/01",
            account_fiscal_end="03/31",
        )
        assert "DROP SCHEMA" not in fetch.captured["query"]
        assert fetch.captured["params"][0] == "'; DROP SCHEMA trd365; --"


class TestFiscalYearRange:
    """A port of dateFunction.ts:calculateFiscalYearDateRange."""

    def test_a_year_that_straddles_the_calendar_boundary_starts_in_the_previous_one(self):
        # April to March: fiscal 2025 runs 2024-04-01 to 2025-03-31.
        assert subcon.fiscal_year_range("04", "03", 2025, "01", "31") == (
            "2024-04-01",
            "2025-03-31",
        )

    def test_a_year_inside_one_calendar_year_does_not(self):
        assert subcon.fiscal_year_range("01", "12", 2025, "01", "31") == (
            "2025-01-01",
            "2025-12-31",
        )

    def test_equal_months_are_treated_as_straddling(self):
        # start === end takes the same branch as start > end in the original.
        assert subcon.fiscal_year_range("06", "06", 2025, "01", "30") == (
            "2024-06-01",
            "2025-06-30",
        )

    def test_single_digit_months_and_days_are_padded(self):
        assert subcon.fiscal_year_range("4", "3", 2025, "1", "5") == ("2024-04-01", "2025-03-05")

    @pytest.mark.parametrize(
        ("start_month", "end_month", "expect_previous_year"),
        [("04", "03", True), ("07", "06", True), ("01", "12", False), ("02", "11", False)],
    )
    def test_the_boundary_rule(self, start_month, end_month, expect_previous_year):
        start, _ = subcon.fiscal_year_range(start_month, end_month, 2025, "01", "28")
        assert start.startswith("2024" if expect_previous_year else "2025")
