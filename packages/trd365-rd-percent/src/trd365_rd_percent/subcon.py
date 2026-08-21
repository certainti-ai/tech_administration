"""
Resolving a project's sub-contractor QRE cap.

A port of ``entity-module/src/utils/subConPercentResolver.ts`` at 6e16f32, which
the legacy JavaScript tool does not implement at all. Sub-contractor QRE is capped
at the percentage configured for the project's jurisdiction (TRDV2-451), and
without this the cap is silently 100%.

The resolution, in order:

1. no country or no account fiscal dates -> the fallback;
2. no Federal R&D Credit configuration for that country -> the fallback;
3. otherwise, of the configurations for that country, the most recent one whose
   effective window overlaps the project's fiscal year — and if none overlaps,
   the most recent one regardless, because a stale cap is closer to right than a
   flat constant;
4. the percentage is read from that configuration's JSON under a key that depends
   on the country, and a missing or non-numeric value -> the fallback.

Every one of those four is reproduced. They are not defensive noise: three of them
are paths the application logs and continues from, so a project sitting on any of
them has real stored numbers that were computed that way.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA

from .calculation import FALLBACK_SUB_CON_PERCENT

#: ``entity-module/src/utils/constants.ts:32``.
FEDERAL_RD_CREDIT_PROGRAM_NAME = "Federal R&D Credit"

#: Which key inside a configuration's JSON holds the cap, per country.
#: ``constants.ts:33-37``. The comments are the product's, not mine: USA uses the
#: regular research credit rather than the alternative simplified credit, and the
#: Canadian federal programme has no ``sub_con_percent`` key at all.
SUB_CON_PERCENT_KEY_BY_COUNTRY_CODE: dict[str, str] = {
    "USA": "rrc_sub_con_percent",
    "CAN": "subcon_qre_adjustment",
}
DEFAULT_SUB_CON_PERCENT_KEY = "sub_con_percent"

#: ``constants.ts:3001`` (``rawQueries.fetchFederalSubConConfigs``), parameterised
#: rather than interpolated — the original builds this by string concatenation.
CONFIG_QUERY = f"""
SELECT ctry.country_code, rv.config_json, rv.effective_start_date, rv.effective_end_date
FROM {DEFAULT_MAIN_SCHEMA}.rd_credit_config_group rg
JOIN {DEFAULT_MAIN_SCHEMA}.rd_credit_parameter_values rv
     ON rv.credit_config_group_rid = rg.rid
JOIN {DEFAULT_MAIN_SCHEMA}.country ctry ON ctry.rid = rg.country_rid
WHERE rg.country_rid = %s
  AND rg.credit_program_name = %s
  AND rg.is_federal = true
  AND rg.state_rid IS NULL
  AND rv.status_rid = (
        SELECT rid FROM {DEFAULT_MAIN_SCHEMA}.status WHERE status_description = 'active'
      )
ORDER BY rv.effective_start_date DESC
"""


@dataclass(frozen=True)
class Resolution:
    """The cap, and why it is that."""

    percent: float
    reason: str

    @property
    def is_fallback(self) -> bool:
        return self.reason != "configured"


def fiscal_year_range(
    start_month: str, end_month: str, fiscal_year: int, start_day: str, end_day: str
) -> tuple[str, str]:
    """
    The calendar dates a fiscal year covers, from the account's fiscal boundaries.

    A port of ``dateFunction.ts:calculateFiscalYearDateRange``. The rule: when the
    start month is after the end month — or the same as it — the year straddles the
    calendar boundary and starts in the *previous* calendar year. A fiscal year
    ending 03/31 in 2025 therefore runs 2024-04-01 to 2025-03-31.
    """
    start = int(start_month)
    end = int(end_month)
    if start >= end:
        return (
            f"{fiscal_year - 1}-{start_month.zfill(2)}-{start_day.zfill(2)}",
            f"{fiscal_year}-{end_month.zfill(2)}-{end_day.zfill(2)}",
        )
    return (
        f"{fiscal_year}-{start_month.zfill(2)}-{start_day.zfill(2)}",
        f"{fiscal_year}-{end_month.zfill(2)}-{end_day.zfill(2)}",
    )


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def _overlaps(config: dict[str, Any], window_start: date, window_end: date) -> bool:
    """
    Whether a configuration's effective window overlaps the fiscal year.

    ``subConPercentResolver.ts:19-27``. An open end is treated as open, not as
    "not yet started" or "already over": a configuration with no start date
    applies to everything before its end, and one with no end applies for ever.
    """
    start = _as_date(config.get("effective_start_date"))
    end = _as_date(config.get("effective_end_date"))
    return (start is None or start <= window_end) and (end is None or end >= window_start)


def resolve(
    fetch: Callable[[str, list], list[tuple]],
    *,
    country_rid: str | None,
    fiscal_year: int | None,
    account_fiscal_start: str | None,
    account_fiscal_end: str | None,
) -> Resolution:
    """
    The cap for one project fiscal, and the reason it came out that way.

    ``fetch(query, params)`` runs a read against the main database. The reason is
    carried alongside the number because three of the four outcomes are fallbacks
    that the application logs and continues from — so an operator seeing an
    unexpected QRE figure needs to know which one applied, and the run report
    should say.
    """
    if not country_rid or not account_fiscal_start or not account_fiscal_end:
        return Resolution(
            FALLBACK_SUB_CON_PERCENT,
            "no country or account fiscal dates on the project; using the fallback",
        )

    rows = fetch(CONFIG_QUERY, [country_rid, FEDERAL_RD_CREDIT_PROGRAM_NAME])
    if not rows:
        return Resolution(
            FALLBACK_SUB_CON_PERCENT,
            f"no Federal R&D Credit configuration for country {country_rid}; using the fallback",
        )

    configs = [
        {
            "country_code": row[0],
            "config_json": row[1],
            "effective_start_date": row[2],
            "effective_end_date": row[3],
        }
        for row in rows
    ]

    start_month, start_day = str(account_fiscal_start).split("/")
    end_month, end_day = str(account_fiscal_end).split("/")
    window = fiscal_year_range(start_month, end_month, int(fiscal_year or 0), start_day, end_day)
    window_start, window_end = _as_date(window[0]), _as_date(window[1])

    # Ordered by effective_start_date DESC by the query, so the first overlap is
    # the most recent applicable one. With no overlap the application falls back to
    # the most recent configuration rather than the flat constant — a stale cap
    # being closer to right than no cap at all.
    applicable = next(
        (c for c in configs if _overlaps(c, window_start, window_end)),
        configs[0],
    )
    overlapped = applicable is not configs[0] or _overlaps(configs[0], window_start, window_end)

    country_code = applicable["country_code"]
    key = SUB_CON_PERCENT_KEY_BY_COUNTRY_CODE.get(country_code, DEFAULT_SUB_CON_PERCENT_KEY)
    payload = applicable["config_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    try:
        percent = float((payload or {})[key])
    except (KeyError, TypeError, ValueError):
        return Resolution(
            FALLBACK_SUB_CON_PERCENT,
            f"key {key!r} missing or not a number in the {country_code} configuration; "
            f"using the fallback",
        )

    if not overlapped:
        return Resolution(
            percent,
            f"no configuration covers fiscal {fiscal_year}; using the most recent "
            f"{country_code} one",
        )
    return Resolution(percent, "configured")
