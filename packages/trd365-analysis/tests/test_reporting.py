"""The reports, which are the only artefact of a run that outlives the terminal."""

from __future__ import annotations

import csv

from trd365_core.datamodel import SchemaCatalog
from trd365_core.model_snapshot import ModelSnapshot, SchemaModel

from trd365_analysis import deviations as dev
from trd365_analysis import reporting
from trd365_analysis.orphans import Orphan, SchemaScan


def snapshot(deviations=None) -> ModelSnapshot:
    catalog = SchemaCatalog.from_columns(
        "orgdb",
        "trd365_1",
        [("project", "rid"), ("a", "rid"), ("a", "projekt_rid"), ("b", "rid"), ("b", "entity_rid")],
    )
    return ModelSnapshot(
        environment="dev",
        generated_at="2026-08-20T00:00:00+00:00",
        generated_by="test",
        schemas={
            "trd365_1": SchemaModel(
                schema="trd365_1",
                catalog=catalog,
                deviations=deviations if deviations is not None else {"projekt": dev.TYPO},
            )
        },
    )


def scans() -> list[SchemaScan]:
    return [
        SchemaScan(
            schema="trd365_1",
            edges_checked=4,
            excluded_parents=["interaction_type"],
            orphans=[
                Orphan(
                    schema="trd365_1",
                    child_table="project_history",
                    column="project_rid",
                    entity="project",
                    parent_table="project",
                    rows=12,
                    samples=["p9", "p8"],
                ),
                Orphan(
                    schema="trd365_1",
                    child_table="case_history",
                    column="case_rid",
                    entity="case",
                    parent_table="cases",
                    rows=0,
                    error="RuntimeError: permission denied",
                ),
            ],
        )
    ]


def test_the_orphans_csv_keeps_the_legacy_column_names(tmp_path):
    # Operators have spreadsheets and filters built on these headers.
    path = reporting.write_orphans_csv(scans(), tmp_path / "o.csv")
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert list(rows[0]) == reporting.ORPHAN_COLUMNS
    assert rows[0]["child_table"] == "project_history"
    assert rows[0]["rows"] == "12"
    assert rows[0]["samples"] == "p9; p8"


def test_an_edge_that_failed_is_in_the_csv_with_its_reason(tmp_path):
    path = reporting.write_orphans_csv(scans(), tmp_path / "o.csv")
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    failed = next(r for r in rows if r["child_table"] == "case_history")
    assert "permission denied" in failed["error"]


def test_the_deviations_csv_lists_the_actionable_ones_first(tmp_path):
    model = snapshot({"projekt": dev.TYPO, "entity": dev.POLYMORPHIC})
    path = reporting.write_deviations_csv(model, tmp_path / "d.csv")
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["classification"] == dev.TYPO
    assert rows[0]["column"] == "projekt_rid"
    assert rows[0]["prefix"] == "projekt"


def test_deviation_counts_are_the_dashboard_metric():
    model = snapshot({"projekt": dev.TYPO, "entity": dev.POLYMORPHIC})
    assert reporting.deviation_counts(model) == {dev.TYPO: 1, dev.POLYMORPHIC: 1}


def test_the_summary_carries_the_fingerprint_so_a_change_is_detectable():
    digest = reporting.summary(snapshot(), scans(), [])
    assert digest["fingerprint"]
    assert digest["version"]
    assert digest["orphans"]["orphan_rows"] == 12


def test_the_summary_says_when_no_scan_ran():
    assert reporting.summary(snapshot(), [], [])["orphans"] is None


def test_the_text_report_leads_with_the_typos():
    text = reporting.render_text(snapshot(), scans(), [])
    assert "LIKELY TYPOS" in text
    assert "trd365_1.a.projekt_rid" in text


def test_the_text_report_shows_the_worst_orphan_edges():
    text = reporting.render_text(snapshot(), scans(), [])
    assert "worst edges:" in text
    assert "project_history.project_rid" in text


def test_the_text_report_says_when_edges_could_not_be_checked():
    assert "1 edge(s) could not be checked" in reporting.render_text(snapshot(), scans(), [])


def test_the_text_report_says_when_no_scan_ran():
    assert "orphan scan: not performed" in reporting.render_text(snapshot(), [], [])


def test_withdrawn_false_alarms_are_called_out():
    changes = [
        dev.Reclassification(
            schema="trd365_1", prefix="projec", was=dev.TYPO, now=dev.GLOBAL_LOOKUP
        )
    ]
    text = reporting.render_text(snapshot(), scans(), changes)
    assert "withdrawing 1 false typo(s)" in text
    assert "projec: typo -> global-lookup" in text


def test_write_reports_returns_every_path_it_wrote(tmp_path):
    paths = reporting.write_reports(snapshot(), scans(), [], tmp_path)
    assert set(paths) == {"text", "deviations", "orphans"}
    assert all(p.exists() for p in paths.values())


def test_write_reports_omits_the_orphans_csv_when_nothing_was_scanned(tmp_path):
    paths = reporting.write_reports(snapshot(), [], [], tmp_path)
    assert "orphans" not in paths
